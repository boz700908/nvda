# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2015-2025 NV Access Limited, Joseph Lee, James Teh
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

"""App module for Start menu/Windows Search/Cortana user interface in Windows 10 Version 1909 and earlier.
This app module also serves as the basis for Start menu in Windows 10 Version 2004 and later
as well as Windows 11, represented by alias app modules.
"""

import appModuleHandler
import controlTypes
import winVersion
import winUser
from logHandler import log
from NVDAObjects import NVDAObject
from NVDAObjects.IAccessible import IAccessible, ContentGenericClient
from NVDAObjects.UIA import UIA, SearchField, SuggestionListItem


class StartMenuSearchField(SearchField):
	# #7370: do not announce text when start menu (searchui) closes.
	announceNewLineText = False

	def _get_description(self) -> str:
		# #13841: detect search highlights and anounce it.
		if self.lastChild.UIAAutomationId == "PlaceholderTextContentPresenter":
			return self.lastChild.name
		return super().description


class StartChromiumObj(IAccessible):
	def _get_shouldAllowIAccessibleFocusEvent(self) -> bool:
		if self.role == controlTypes.Role.DOCUMENT:
			# #17951: Sometimes, the results Chromium document fires a focus event and
			# reports as focused, even though the search box still has focus. We can
			# tell whether it is *really* focused by checking whether its
			# Windows.UI.Core.CoreComponentInputSource ancestor has focus.
			try:
				return self.parent.parent.parent.hasFocus
			except AttributeError:
				log.debugWarning("Couldn't find CoreInput ancestor of Chromium doc")
		return super().shouldAllowIAccessibleFocusEvent

	def isDescendantOf(self, obj: NVDAObject) -> bool:
		# #17951: We use IA2 for the Chromium document. However, this method will be
		# called with the UIA object being controlled by the search box to check
		# whether it is a suggestion.
		return (
			isinstance(obj, UIA) and obj.UIAElement.CurrentClassName == "WebView2Standalone.Controls.WebView2"
		)


class AppModule(appModuleHandler.AppModule):
	def event_NVDAObject_init(self, obj):
		if isinstance(obj, UIA):
			# #10341: Build 18363 introduces modern search experience in File Explorer.
			# As part of this, suggestion count is part of a live region.
			# Although it is geared for Narrator, it is applicable to other screen readers as well.
			# The live region itself is a child of the one shown here.
			if (
				winVersion.getWinVer() >= winVersion.WIN10_1909
				and obj.UIAAutomationId == "suggestionCountForNarrator"
				and obj.firstChild is not None
			):
				obj.name = obj.firstChild.name

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if isinstance(obj, IAccessible):
			try:
				# #5288: Never use ContentGenericClient, as this uses displayModel
				# which will freeze if the process is suspended.
				clsList.remove(ContentGenericClient)
			except ValueError:
				pass
			if obj.windowClassName.startswith("Chrome_"):
				clsList.insert(0, StartChromiumObj)
		elif isinstance(obj, UIA):
			if obj.UIAAutomationId == "SearchTextBox":
				clsList.insert(0, StartMenuSearchField)
			# #10329: Since 2019, some suggestion items are grouped inside another suggestions list item.
			# #13544: grandparent must be checked due to redesign in 2019.
			# Because of this, result details will not be announced like in the past.
			elif obj.role == controlTypes.Role.LISTITEM and (
				isinstance(obj.parent, SuggestionListItem)
				or isinstance(obj.parent.parent, SuggestionListItem)
			):
				clsList.insert(0, SuggestionListItem)

	def isBadUIAWindow(self, hwnd: int) -> bool:
		# #17951: Never use UIA for the Chromium document in the Start menu because
		# SetFocus freezes. Without this explicit code, NVDA would try to use UIA:
		# 1. If we haven't injected yet. This can happen before focus is fired
		# within the Chromium document. Since it is in a different process, it
		# doesn't fire foreground and focus events as soon as the Start Menu opens.
		# 2. If we can't inject at all, which happens if we don't have the uiAccess
		# privilege.
		return winUser.getClassName(hwnd) == "Chrome_RenderWidgetHostHWND"
