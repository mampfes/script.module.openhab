# coding=utf-8

import xbmcaddon
import xbmcgui


# selectdialog.xml control ID's
CONTROL_ID_PANEL = 100

# xbmcgui action codes to go up/back in a window
WINDOW_EXIT_CODES = frozenset([xbmcgui.ACTION_PARENT_DIR,
                               xbmcgui.ACTION_PREVIOUS_MENU,
                               xbmcgui.ACTION_NAV_BACK,
                               xbmcgui.KEY_BUTTON_BACK])


class ColorPicker(xbmcgui.WindowXMLDialog):
    def __new__(cls, title, color):
        return super(ColorPicker, cls).__new__(cls, "colorpicker.xml", xbmcaddon.Addon().getAddonInfo('path'))

    # init window
    def __init__(self, title, color):
        super(ColorPicker, self).__init__(title, color)
        self.control = None
        self.title = title
        self.color = color
        self.result = None
        self.listitems = []
        self.colors = ['AC3832',
                       'FA443B',
                       'F86B64',
                       'F9ADAA',
                       '000000',
                       'B78538',
                       'FF9845',
                       'FFAF51',
                       'FFD39F',
                       '222222',
                       'B3AA3F',
                       'ECE351',
                       'FFF65F',
                       'FFF9A5',
                       '444444',
                       '659247',
                       '8DD45D',
                       'A5DC7E',
                       'CBEAB8',
                       '666666',
                       '48885D',
                       '5FC27D',
                       '80CE98',
                       'B9E4C8',
                       '888888',
                       '488B8E',
                       '61CACE',
                       '83D4D7',
                       'B9E7E9',
                       'AAAAAA',
                       '326492',
                       '3989D3',
                       '63A2DC',
                       'AACBEC',
                       'CCCCCC',
                       '5E3F7A',
                       '7F50AB',
                       '9975BD',
                       'C7B2DA',
                       'EEEEEE',
                       '883C77',
                       'C24BA9',
                       'CE72BA',
                       'E3B0D9',
                       'FFFFFF']

    def show(self):
        self.doModal()
        return self.result

    def set_title(self, title):
        self.title = title
        if self.control:
            self.setProperty('title', self.title)

    def set_color(self, color):
        try:
            index = self.colors.index(self.color)
            self.listitems[index].select(False)
        except ValueError:
            pass

        self.color = color

        try:
            index = self.colors.index(self.color)
            self.listitems[index].select(True)
        except ValueError:
            pass

    # window init callback
    def onInit(self):
        self.control = self.getControl(CONTROL_ID_PANEL)
        self.setProperty('title', self.title)
        self.build_list()
        self.setFocusId(CONTROL_ID_PANEL)

    def build_list(self):
        self.control.reset()
        for c in self.colors:
            li = xbmcgui.ListItem(label=c, thumbnailImage='colors/FF' + c + '.png')
            self.listitems.append(li)
            self.control.addItem(li)

        try:
            index = self.colors.index(self.color)
            self.listitems[index].select(True)      # set selected flag
            self.control.selectItem(index)          # move focus to selected item
        except ValueError:
            pass

    # window action callback
    def onAction(self, action):
        if action.getId() in WINDOW_EXIT_CODES:
            self.close()

    # mouse click action
    def onClick(self, controlId):
        if controlId == CONTROL_ID_PANEL:
            self.result = self.colors[self.control.getSelectedPosition()]
        self.close()