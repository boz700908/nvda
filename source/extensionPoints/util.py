# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2017-2025 NV Access Limited, Leonard de Ruijter
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

"""Utilities used withing the extension points framework. Generally it is expected that the class in __init__.py are
used, however for more advanced requirements these utilities can be used directly.
"""

# "annotations" Needed to reference BoundMethodWeakref in one of the init params of itself.
from __future__ import annotations
import weakref
import inspect
from typing import (
	Callable,
	Generator,
	Generic,
	Optional,
	OrderedDict,
	Tuple,
	TypeVar,
	Union,
)

import NVDAState

from logHandler import log

HandlerT = TypeVar("HandlerT", bound=Callable)
HandlerKeyT = Union[int, Tuple[int, int]]


class AnnotatableWeakref(weakref.ref, Generic[HandlerT]):
	"""A weakref.ref which allows annotation with custom attributes."""

	handlerKey: int


class BoundMethodWeakref(Generic[HandlerT]):
	"""Weakly references a bound instance method.
	Instance methods are bound dynamically each time they are fetched.
	weakref.ref on a bound instance method doesn't work because
	as soon as you drop the reference, the method object dies.
	Instead, this class holds weak references to both the instance and the function,
	which can then be used to bind an instance method.
	To get the actual method, you call an instance as you would a weakref.ref.
	"""

	handlerKey: Tuple[int, int]

	def __init__(
		self,
		target: HandlerT,
		onDelete: Optional[Callable[[BoundMethodWeakref], None]] = None,
	):
		if onDelete:

			def onRefDelete(weak):
				"""Calls onDelete for our BoundMethodWeakref when one of the individual weakrefs (instance or function) dies."""
				onDelete(self)
		else:
			onRefDelete = None
		inst = target.__self__
		func = target.__func__
		self.weakInst = weakref.ref(inst, onRefDelete)
		self.weakFunc = weakref.ref(func, onRefDelete)

	def __call__(self) -> Optional[HandlerT]:
		inst = self.weakInst()
		if not inst:
			return
		func = self.weakFunc()
		assert func, "inst is alive but func is dead"
		# Get an instancemethod by binding func to inst.
		return func.__get__(inst)


def _getHandlerKey(handler: Callable) -> HandlerKeyT:
	"""Get a key which identifies a handler function.
	This is needed because we store weak references, not the actual functions.
	We store the key on the weak reference.
	When the handler dies, we can use the key on the weak reference to remove the handler.
	"""
	inst = getattr(handler, "__self__", None)
	if inst:
		return (id(inst), id(handler.__func__))
	return id(handler)


class HandlerRegistrar(Generic[HandlerT]):
	"""Base class to Facilitate registration and unregistration of handler functions.
	The handlers are stored using weak references and are automatically unregistered
	if the handler dies.
	Both normal functions, instance methods and lambdas are supported. Ensure to keep lambdas alive by maintaining a
	reference to them.
	The handlers are maintained in the order they were registered
	so that they can be called in a deterministic order across runs.
	This class doesn't provide any functionality to actually call the handlers.
	If you want to implement an extension point,
	you probably want the L{Action} or L{Filter} subclasses instead.
	"""

	def __init__(self, *, _deprecationMessage: str | None = None):
		"""Initialise the handler registrar.

		:param _deprecationMessage: Optional deprecation message to be logged when :method:`register` is called on the handler.
		"""
		self._deprecationMessage = _deprecationMessage
		#: Registered handler functions.
		#: This is an OrderedDict where the keys are unique identifiers (as returned by _getHandlerKey)
		#: and the values are weak references.
		self._handlers = OrderedDict[
			HandlerKeyT,
			Union[BoundMethodWeakref[HandlerT], AnnotatableWeakref[HandlerT]],
		]()

	def register(self, handler: HandlerT):
		"""You can register functions, bound instance methods, class methods, static methods or lambdas.
		However, the callable must be kept alive by your code otherwise it will be de-registered.
		This is due to the use of weak references.
		This is especially relevant when using lambdas.
		"""
		if inspect.isfunction(handler):
			sig = inspect.signature(handler)
			if sig.parameters and list(sig.parameters)[0] == "self":
				raise TypeError("Registering unbound instance methods not supported.")
		if self._deprecationMessage:
			if NVDAState._allowDeprecatedAPI():
				log.warning(self._deprecationMessage, stack_info=True)
			else:
				raise RuntimeError(self._deprecationMessage)
		if inspect.ismethod(handler):
			weak = BoundMethodWeakref(handler, self.unregister)
		else:
			weak = AnnotatableWeakref(handler, self.unregister)
		key = _getHandlerKey(handler)
		# Store the key on the weakref so we can remove the handler when it dies.
		weak.handlerKey = key
		self._handlers[key] = weak

	def moveToEnd(self, handler: HandlerT, last: bool = False) -> bool:
		"""Move a registered handler to the start or end of the collection with registered handlers.
		This can be used to modify the order in which handlers are called.
		@param last: Whether to move the handler to the end.
			If C{False} (default), the handler is moved to the start.
		@returns: Whether the handler was found.
		"""
		if isinstance(handler, (AnnotatableWeakref, BoundMethodWeakref)):
			key = handler.handlerKey
		else:
			key = _getHandlerKey(handler)
		try:
			self._handlers.move_to_end(key=key, last=last)
		except KeyError:
			return False
		return True

	def unregister(
		self,
		handler: Union[AnnotatableWeakref[HandlerT], BoundMethodWeakref[HandlerT], HandlerT],
	):
		if isinstance(handler, (AnnotatableWeakref, BoundMethodWeakref)):
			key = handler.handlerKey
		else:
			key = _getHandlerKey(handler)
		try:
			del self._handlers[key]
		except KeyError:
			return False
		return True

	@property
	def handlers(self) -> Generator[HandlerT, None, None]:
		"""Generator of registered handler functions.
		This should be used when you want to call the handlers.
		"""
		for weak in self._handlers.values():
			handler = weak()
			if not handler:
				continue  # Died.
			yield handler


def callWithSupportedKwargs(func, *args, **kwargs):
	"""Call a function with only the keyword arguments it supports.
	For example, if myFunc is defined as:
	C{def myFunc(a=None, b=None):}
	and you call:
	C{callWithSupportedKwargs(myFunc, a=1, b=2, c=3)}
	Instead of raising a TypeError, myFunc will simply be called like this:
	C{myFunc(a=1, b=2)}

	C{callWithSupportedKwargs} does support positional arguments (C{*args}).
	Unfortunately, positional args can not be matched on name (keyword)
	to the names of the params in the handler.
	Therefore, usage is strongly discouraged due to the
	risk of parameter order differences causing bugs.

	@param func: can be any callable that is not an unbound method. EG:
		- Bound instance methods
		- class methods
		- static methods
		- functions
		- lambdas
		- partials

		The arguments for the supplied callable, C{func}, do not need to have default values, and can take C{**kwargs} to
		capture all arguments.
		See C{tests/unit/test_extensionPoints.py:TestCallWithSupportedKwargs} for examples.

		An exception is raised if:
			- the number of positional arguments given can not be received by C{func}.
			- parameters required (parameters declared with no default value) by C{func} are not supplied.
	"""
	sig = inspect.signature(func)

	if inspect.isfunction(func) and sig.parameters and list(sig.parameters)[0] == "self":
		raise TypeError("Unbound instance methods are not handled.")

	# Check whether func has a catch-all for kwargs (**kwargs)
	# In this case, we do not need to filter to just the supported args.
	if not any(param for param in sig.parameters.values() if param.kind == param.VAR_KEYWORD):
		# Delete all the kwargs that are not supported by this callable.
		# Wrap the items call in a list, as the dictionary changes during iteration.
		for kwarg in list(kwargs.keys()):
			if kwarg not in sig.parameters:
				del kwargs[kwarg]

	boundArguments = sig.bind(*args, **kwargs)
	return func(*boundArguments.args, **boundArguments.kwargs)
