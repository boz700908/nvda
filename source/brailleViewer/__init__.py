# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2014-2025 NV Access Limited, Leonard de Ruijter
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

import typing

import gui
import extensionPoints
import config

from .brailleViewerGui import BrailleViewerFrame

if typing.TYPE_CHECKING:
	from braille import DisplayDimensions

"""
### Overview
This package contains the components for a "Braille Viewer". A window, that shows the braille dots that
would be displayed on a hardware device. The raw text for each cell is also shown.
This tool consists of:
- A GUI for the viewer.
- Construction / destruction / update helpers.

The current intention is to be able to support a physical braille device while using the "Braille Viewer".
Due to limitations in the design of brailleHandler, the number of cells in the "Braille Viewer" must match any
connected physical device.

### Life-cycle
- Constructing / showing the BrailleViewer
	- On startup via L{core.doStartupDialogs}
	- Via NVDA (tools) menu via L{Mainframe.onToggleSpeechViewerCommand}
- Hiding / destroying the BrailleViewer
	- On exit of NVDA.
	- Via NVDA (tools) menu via L{Mainframe.onToggleSpeechViewerCommand}
	- When the Window receives a close event. This means the GUI must be able to call-back to clean up
	BrailleHandler and the NVDA tools menu. This callback happens via the L{postBrailleViewerToolToggledAction}

### Number of cells shown
The default (40) is set in L{createBrailleViewerTool}.

### Routing
Currently not supported.
In order to support routing the user must be able to click on the cells. This means that the BrailleViewer
window gains focus, and the braille values are changed. To avoid this would require substantial changes to
brailleHandler.

### Scrolling
Scrolling is supported by binding a gesture to the braille_scroll_forward and braille scroll_back commands.
For the same reason that Routing is not supported, scrolling via button clicks on the braille viewer window
is not supported.

"""

# global braille viewer driver:
_brailleGui: BrailleViewerFrame | None = None

# Extension points action:
# Triggered every time the Braille Viewer is created / shown or hidden / destroyed.
# Callback definition: Callable(created: bool) -> None
#   created - True for created/shown, False for hidden/destroyed.
postBrailleViewerToolToggledAction = extensionPoints.Action()
DEFAULT_NUM_CELLS = config.conf["brailleViewer"]["defaultCellCount"]


def isBrailleViewerActive() -> bool:
	return bool(_brailleGui)


def destroyBrailleViewer():
	global _brailleGui
	d: BrailleViewerFrame | None = _brailleGui
	_brailleGui = None  # protect against re-entrance
	if d is not None:
		import braille  # imported late to avoid a circular import.

		if not d.isDestroyed:
			updateBrailleDisplayedUnregistered = braille.pre_writeCells.unregister(d.updateBrailleDisplayed)
			assert updateBrailleDisplayedUnregistered
			d.saveInfoAndDestroy()
		getDisplayDimensionsUnregistered = braille.filter_displayDimensions.unregister(_getDisplayDimensions)
		assert getDisplayDimensionsUnregistered


def _onGuiDestroyed():
	"""Used as a callback from L{BrailleViewerFrame}, lets us know that the GUI initiated a destruction."""
	# In case this destruction wasn't initiated by L{destroyBrailleViewer}, do any necessary clean up.
	# the destruction may have been triggered by alt+F4 on the window,
	# or selecting close from the taskbar jumplist.
	destroyBrailleViewer()
	# Ensure that the GUI knows about it
	postBrailleViewerToolToggledAction.notify(created=False)


def _getDisplayDimensions(dimensions: "DisplayDimensions") -> "DisplayDimensions":
	"""Called by the :attr:`braille.filter_displayDimensions` extension point to get the display dimensions."""
	from braille import DisplayDimensions  # imported late to avoid a circular import.

	return DisplayDimensions(
		numRows=1,
		numCols=dimensions.displaySize if dimensions.displaySize > 0 else DEFAULT_NUM_CELLS,
	)


@gui.blockAction.when(gui.blockAction.Context.SECURE_MODE)
def createBrailleViewerTool():
	if not gui.mainFrame:
		raise RuntimeError("Can not initialise the BrailleViewerGui: gui.mainFrame not yet initialised")

	import braille  # imported late to avoid a circular import.

	if not braille.handler:
		raise RuntimeError("Can not initialise the BrailleViewerGui: braille.handler not yet initialised")

	braille.filter_displayDimensions.register(_getDisplayDimensions)

	global _brailleGui
	if _brailleGui:
		destroyBrailleViewer()

	_brailleGui = BrailleViewerFrame(
		braille.handler.displaySize,
		_onGuiDestroyed,
	)
	braille.pre_writeCells.register(_brailleGui.updateBrailleDisplayed)
	postBrailleViewerToolToggledAction.notify(created=True)
