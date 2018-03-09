# Copyright 2015 Adobe. All rights reserved.

# TODO:
# add support for ligatures
# add support for accents with multiple anchors
# - this will require significant changes to the WriteFeaturesMarkFDK module

from itertools import product
from mojo.roboFont import CurrentFont, CurrentGlyph, RGlyph, AllFonts
from mojo.roboFont import version as roboFontVersion
from mojo.drawingTools import (newPath, moveTo, lineTo, curveTo, closePath,
                               drawPath, translate, fill, strokeWidth)
from mojo.events import addObserver, removeObserver
from mojo.extensions import getExtensionDefault, setExtensionDefault
from mojo.UI import UpdateCurrentGlyphView, MultiLineView, OutputWindow
from vanilla import (FloatingWindow, List, TextBox, EditText, CheckBox, Group,
                     HorizontalLine, ScrollView)
from defconAppKit.windows.baseWindow import BaseWindowController
from fontTools.pens.basePen import BasePen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Identity
from defconAppKit.controls.openTypeControlsView import (
    DefconAppKitTopAnchoredNSView)
from AppKit import NSNumber, NSNumberFormatter, NSBeep, NSNoBorder

extensionKey = "com.adobe.AdjustAnchors"
extensionName = "Adjust Anchors"

# NOTE: Contextual anchors on mark glyphs are currently NOT supported
CONTEXTUAL_ANCHOR_TAG = "CXT"


class AdjustAnchors(BaseWindowController):

    def __init__(self):
        self.font = CurrentFont()
        self.glyph = CurrentGlyph()
        self.upm = self.font.info.unitsPerEm
        # key: glyph name -- value: list containing assembled glyphs
        self.glyphPreviewCacheDict = {}
        # key: anchor name -- value: list of mark glyph names
        self.anchorsOnMarksDict = {}
        # key: anchor name -- value: list of base glyph names
        self.anchorsOnBasesDict = {}
        self.CXTanchorsOnBasesDict = {}
        # key: mark glyph name -- value: anchor name
        # NOTE: It's expected that each mark glyph only has one type of anchor
        self.marksDict = {}
        self.fillAnchorsAndMarksDicts()
        # list of glyph names that will be displayed in the UI list
        self.glyphNamesList = []
        # list of glyph names selected in the UI list
        self.selectedGlyphNamesList = []
        # list of the glyph objects that should be inserted
        # before and after the accented glyphs
        self.extraGlyphsList = []

        self.Blue, self.Alpha = 1, 0.6

        self.font.naked().addObserver(self, "fontWasModified", "Font.Changed")
        addObserver(self, "_fontWillClose", "fontWillClose")
        addObserver(self, "_currentFontChanged", "fontResignCurrent")
        addObserver(self, "_currentGlyphChanged", "currentGlyphChanged")
        addObserver(self, "_drawFill", "draw")
        addObserver(self, "_drawFill", "drawInactive")
        addObserver(self, "_previewFill", "drawPreview")
        # observer for the draw event
        addObserver(self, "_drawGlyphs", "draw")
        # draw the glyphs when the glyph window is not in focus
        addObserver(self, "_drawGlyphs", "drawInactive")
        addObserver(self, "_drawGlyphs", "drawPreview")

        integerNumFormatter = NSNumberFormatter.alloc().init()
        integerNumFormatter.setAllowsFloats_(False)
        integerNumFormatter.setGeneratesDecimalNumbers_(False)

        intPosMinZeroNumFormatter = NSNumberFormatter.alloc().init()
        intPosMinZeroNumFormatter.setAllowsFloats_(False)
        intPosMinZeroNumFormatter.setGeneratesDecimalNumbers_(False)
        intPosMinZeroNumFormatter.setMinimum_(NSNumber.numberWithInt_(0))

        intPosMinOneNumFormatter = NSNumberFormatter.alloc().init()
        intPosMinOneNumFormatter.setAllowsFloats_(False)
        intPosMinOneNumFormatter.setGeneratesDecimalNumbers_(False)
        intPosMinOneNumFormatter.setMinimum_(NSNumber.numberWithInt_(1))

        self.textSize = getExtensionDefault(
            "%s.%s" % (extensionKey, "textSize"))
        if not self.textSize:
            self.textSize = 150

        self.lineHeight = getExtensionDefault(
            "%s.%s" % (extensionKey, "lineHeight"))
        if not self.lineHeight:
            self.lineHeight = 200

        self.extraSidebearings = getExtensionDefault(
            "%s.%s" % (extensionKey, "extraSidebearings"))
        if not self.extraSidebearings:
            self.extraSidebearings = [0, 0]

        self.extraGlyphs = getExtensionDefault(
            "%s.%s" % (extensionKey, "extraGlyphs"))
        if not self.extraGlyphs:
            self.extraGlyphs = ''

        posSize = getExtensionDefault(
            "%s.%s" % (extensionKey, "posSize"))
        if not posSize:
            posSize = (100, 100, 1200, 400)

        self.calibrateMode = getExtensionDefault(
            "%s.%s" % (extensionKey, "calibrateMode"))
        if not self.calibrateMode:
            self.calibrateMode = False

        calibrateModeStrings = getExtensionDefault(
            "%s.%s" % (extensionKey, "calibrateModeStrings"))
        if not calibrateModeStrings:
            calibrateModeStrings = {
                'group1.baseInput': 'dotlessi o s',
                'group1.markInput': 'dieresis circumflex macron breve caron',
                'group2.baseInput': 'I O S',
                'group2.markInput': 'dieresis.cap circumflex.cap macron.cap '
                                    'breve.cap caron.cap',
                'group3.baseInput': 'I.sc O.sc S.sc',
                'group3.markInput': 'dieresis circumflex macron breve caron',
                'group4.baseInput': '',
                'group4.markInput': '',
            }

        # -- Window --
        self.w = FloatingWindow(posSize, extensionName, minSize=(500, 400))
        self.w.fontList = List((10, 10, 190, -41), self.glyphNamesList,
                               selectionCallback=self.listSelectionCallback)
        if roboFontVersion < '1.7':
            # use the full width of the column
            self.w.fontList.getNSTableView().sizeToFit()
        self.w.fontList.show(not self.calibrateMode)
        self.w.lineView = MultiLineView((210, 10, -10, -41),
                                        pointSize=self.textSize,
                                        lineHeight=self.lineHeight,
                                        displayOptions={"Beam": False,
                                        "displayMode": "Multi Line"}
                                        )
        self.w.lineView.setFont(self.font)
        # -- Calibration Mode --
        baseLabel = "Bases"
        markLabel = "Marks"
        width, height = 190, 140
        self.cm = Group((0, 0, 0, 0))
        # ---
        self.cm.group1 = Group((5, height * 0, width, height - 10))
        self.cm.group1.baseLabel = TextBox((0, 0, width, 20), baseLabel)
        self.cm.group1.baseInput = EditText(
            (0, 21, width, 22), calibrateModeStrings['group1.baseInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group1.markLabel = TextBox((0, 50, width, 20), markLabel)
        self.cm.group1.markInput = EditText(
            (0, 71, width, 44), calibrateModeStrings['group1.markInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group1.divider = HorizontalLine((0, -1, -0, 1))
        # ---
        self.cm.group2 = Group((5, height * 1, width, height - 10))
        self.cm.group2.baseLabel = TextBox((0, 0, width, 20), baseLabel)
        self.cm.group2.baseInput = EditText(
            (0, 21, width, 22), calibrateModeStrings['group2.baseInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group2.markLabel = TextBox((0, 50, width, 20), markLabel)
        self.cm.group2.markInput = EditText(
            (0, 71, width, 44), calibrateModeStrings['group2.markInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group2.divider = HorizontalLine((0, -1, -0, 1))
        # ---
        self.cm.group3 = Group((5, height * 2, width, height - 10))
        self.cm.group3.baseLabel = TextBox((0, 0, width, 20), baseLabel)
        self.cm.group3.baseInput = EditText(
            (0, 21, width, 22), calibrateModeStrings['group3.baseInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group3.markLabel = TextBox((0, 50, width, 20), markLabel)
        self.cm.group3.markInput = EditText(
            (0, 71, width, 44), calibrateModeStrings['group3.markInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group3.divider = HorizontalLine((0, -1, -0, 1))
        # ---
        self.cm.group4 = Group((5, height * 3, width, height - 10))
        self.cm.group4.baseLabel = TextBox((0, 0, width, 20), baseLabel)
        self.cm.group4.baseInput = EditText(
            (0, 21, width, 22), calibrateModeStrings['group4.baseInput'],
            callback=self.updateCalibrateMode, continuous=False)
        self.cm.group4.markLabel = TextBox((0, 50, width, 20), markLabel)
        self.cm.group4.markInput = EditText(
            (0, 71, width, 44), calibrateModeStrings['group4.markInput'],
            callback=self.updateCalibrateMode, continuous=False)
        # ---
        view = DefconAppKitTopAnchoredNSView.alloc().init()
        view.addSubview_(self.cm.getNSView())
        view.setFrame_(((0, 0), (width + 10, height * 4 - 23)))
        self.cm.setPosSize((0, 0, width + 10, height * 4 - 22))
        self.w.scrollView = ScrollView(
            (5, 10, width + 10, -41), view, drawsBackground=False,
            hasHorizontalScroller=False)
        self.w.scrollView.getNSScrollView().setBorderType_(NSNoBorder)
        # NSScrollElasticityNone
        self.w.scrollView.getNSScrollView().setVerticalScrollElasticity_(1)
        self.w.scrollView.show(self.calibrateMode)

        # -- Footer --
        self.w.calibrateModeCheck = CheckBox(
            (10, -32, 200, -10), "Calibration Mode",
            callback=self.calibrateModeCallback, value=self.calibrateMode)
        self.w.textSizeLabel = TextBox((210, -30, 100, -10), "Text Size")
        self.w.textSize = EditText(
            (270, -32, 35, -10), self.textSize,
            callback=self.textSizeCallback, continuous=False,
            formatter=intPosMinOneNumFormatter)
        self.w.lineHeightLabel = TextBox((320, -30, 100, -10), "Line Height")
        self.w.lineHeight = EditText(
            (395, -32, 35, -10), self.lineHeight,
            callback=self.lineHeightCallback, continuous=False,
            formatter=integerNumFormatter)
        self.w.extraSidebearingsLabel = TextBox((446, -30, 180, -10),
                                                "Extra Sidebearings")
        self.w.extraSidebearingsChar = TextBox((602, -30, 20, -10), "&")
        self.w.extraSidebearingLeft = EditText(
            (567, -32, 35, -10), self.extraSidebearings[0],
            callback=self.extraSidebearingsCallback, continuous=False,
            formatter=intPosMinZeroNumFormatter)
        self.w.extraSidebearingRight = EditText(
            (614, -32, 35, -10), self.extraSidebearings[1],
            callback=self.extraSidebearingsCallback, continuous=False,
            formatter=intPosMinZeroNumFormatter)
        self.w.extraGlyphsLabel = TextBox((665, -30, 180, -10), "Extra Glyphs")
        self.w.extraGlyphs = EditText(
            (749, -32, -10, -10), self.extraGlyphs,
            callback=self.extraGlyphsCallback, continuous=False)

        # trigger the initial state and contents of the window
        self.extraGlyphsCallback()  # calls self.updateExtensionWindow()

        self.w.bind("close", self.windowClose)
        self.w.open()
        self.w.makeKey()

    def calibrateModeCallback(self, sender):
        self.calibrateMode = not self.calibrateMode
        self.w.fontList.show(not sender.get())
        self.w.scrollView.show(self.calibrateMode)
        self.updateExtensionWindow()

    def textSizeCallback(self, sender):
        try:  # in case the user submits an empty field
            self.textSize = int(sender.get())
        except Exception:  # reset to the previous value
            NSBeep()
            self.sender.set(self.textSize)
        self.w.lineView.setPointSize(self.textSize)

    def lineHeightCallback(self, sender):
        try:
            self.lineHeight = int(sender.get())
        except Exception:
            NSBeep()
            self.sender.set(self.lineHeight)
        self.w.lineView.setLineHeight(self.lineHeight)

    def extraSidebearingsCallback(self, sender):
        left = self.w.extraSidebearingLeft
        right = self.w.extraSidebearingRight
        try:
            self.extraSidebearings = [int(left.get()), int(right.get())]
        except Exception:
            NSBeep()
            left.set(self.extraSidebearings[0])
            right.set(self.extraSidebearings[1])
        self.extraGlyphsCallback()  # calls self.updateExtensionWindow()

    def extraGlyphsCallback(self, *sender):
        del self.extraGlyphsList[:]  # empty the list
        self.extraGlyphs = self.w.extraGlyphs.get()
        glyphNamesList = self.extraGlyphs.split()
        for gName in glyphNamesList:
            try:
                extraGlyph = self.font[gName]
                # must create a new glyph in order to be able to
                # increase the sidebearings without modifying the font
                newGlyph = RGlyph()
                newGlyph.setParent(self.font)
                # must use deepAppend because the extra glyph may have
                # components (which will cause problems to the MultiLineView)
                newGlyph = self.deepAppendGlyph(newGlyph, extraGlyph)
                newGlyph.width = extraGlyph.width
            except Exception:
                continue
            newGlyph.leftMargin += self.extraSidebearings[0]
            newGlyph.rightMargin += self.extraSidebearings[1]
            self.extraGlyphsList.append(newGlyph)
        self.glyphPreviewCacheDict.clear()
        self.updateExtensionWindow()

    def windowClose(self, sender):
        self.font.naked().removeObserver(self, "Font.Changed")
        removeObserver(self, "fontWillClose")
        removeObserver(self, "fontResignCurrent")
        removeObserver(self, "currentGlyphChanged")
        removeObserver(self, "draw")
        removeObserver(self, "drawInactive")
        removeObserver(self, "drawPreview")
        self.saveExtensionDefaults()

    def getCalibrateModeStrings(self):
        calibrateModeStringsDict = {}
        for i in range(1, 5):
            group = getattr(self.cm, "group%d" % i)
            calibrateModeStringsDict[
                "group%d.baseInput" % i] = group.baseInput.get()
            calibrateModeStringsDict[
                "group%d.markInput" % i] = group.markInput.get()
        return calibrateModeStringsDict

    def saveExtensionDefaults(self):
        setExtensionDefault("%s.%s" % (extensionKey, "posSize"),
                            self.w.getPosSize())
        setExtensionDefault("%s.%s" % (extensionKey, "textSize"),
                            self.textSize)
        setExtensionDefault("%s.%s" % (extensionKey, "lineHeight"),
                            self.lineHeight)
        setExtensionDefault("%s.%s" % (extensionKey, "extraSidebearings"),
                            self.extraSidebearings)
        setExtensionDefault("%s.%s" % (extensionKey, "extraGlyphs"),
                            self.extraGlyphs)
        setExtensionDefault("%s.%s" % (extensionKey, "calibrateMode"),
                            self.calibrateMode)
        setExtensionDefault("%s.%s" % (extensionKey, "calibrateModeStrings"),
                            self.getCalibrateModeStrings())

    def _previewFill(self, info):
        self.Blue, self.Alpha = 0, 1

    def _drawFill(self, info):
        self.Blue, self.Alpha = 1, 0.6

    def _fontWillClose(self, info):
        """
        Close the window when the last font is closed
        """
        if len(AllFonts()) < 2:
            self.windowClose(self)
            self.w.close()

    def _currentFontChanged(self, info):
        self.font.naked().removeObserver(self, "Font.Changed")
        self.font = CurrentFont()
        self.font.naked().addObserver(self, "fontWasModified", "Font.Changed")
        self.w.lineView.setFont(self.font)
        self.fillAnchorsAndMarksDicts()
        del self.glyphNamesList[:]
        del self.selectedGlyphNamesList[:]
        self.updateExtensionWindow()

    def _currentGlyphChanged(self, info):
        self.updateExtensionWindow()

    def fontWasModified(self, info):
        OutputWindow().clear()
        self.fillAnchorsAndMarksDicts()
        del self.glyphNamesList[:]
        del self.selectedGlyphNamesList[:]
        self.updateExtensionWindow()

    def deepAppendGlyph(self, glyph, gToAppend, offset=(0, 0)):
        if not gToAppend.components:
            glyph.appendGlyph(gToAppend, offset)
        else:
            for component in gToAppend.components:
                # avoid traceback in the case where the selected glyph is
                # referencing a component whose glyph is not in the font
                if component.baseGlyph not in self.font.keys():
                    print("WARNING: %s is referencing a glyph named %s, which "
                          "does not exist in the font." %
                          (self.font.selection[0], component.baseGlyph))
                    continue

                compGlyph = self.font[component.baseGlyph].copy()

                # handle component transformations
                componentTransformation = component.transformation
                # when undoing a paste anchor or a delete anchor action,
                # RoboFont returns component.transformation as a list instead
                # of a tuple
                if type(componentTransformation) is list:
                    componentTransformation = tuple(componentTransformation)
                # if component is skewed and/or is shifted
                if componentTransformation != (1, 0, 0, 1, 0, 0):
                    matrix = componentTransformation[0:4]
                    if matrix != (1, 0, 0, 1):  # if component is skewed
                        # ignore the original component's shifting values
                        transformObj = Identity.transform(matrix + (0, 0))
                        compGlyph.transform(transformObj)

                # add the two tuples of offset
                glyph.appendGlyph(
                    compGlyph, tuple(map(sum, zip(component.offset, offset))))
            for contour in gToAppend:
                glyph.appendContour(contour, offset)

        # if the assembled glyph still has components, recursively
        # remove and replace them 1-by-1 by the glyphs they reference
        if glyph.components:
            nestedComponent = glyph.components[-1]  # start from the end
            glyph.removeComponent(nestedComponent)
            glyph = self.deepAppendGlyph(glyph,
                                         self.font[nestedComponent.baseGlyph],
                                         nestedComponent.offset)
        return glyph

    def updateCalibrateMode(self, *sender):
        glyphsList = []
        newLine = self.w.lineView.createNewLineGlyph()

        # cycle thru the UI Groups and collect the strings
        for i in range(1, 5):
            group = getattr(self.cm, "group%d" % i)
            baseGlyphsNamesList = group.baseInput.get().split()
            markGlyphsNamesList = group.markInput.get().split()

            # iterate thru the base+mark combinations
            for gBaseName, gMarkName in product(baseGlyphsNamesList,
                                                markGlyphsNamesList):
                newGlyph = RGlyph()
                newGlyph.setParent(self.font)
                # skip invalid glyph names
                try:
                    baseGlyph = self.font[gBaseName]
                    markGlyph = self.font[gMarkName]
                except Exception:
                    continue
                # append base glyph
                newGlyph = self.deepAppendGlyph(newGlyph, baseGlyph)
                # append mark glyph
                newGlyph = self.deepAppendGlyph(
                    newGlyph, markGlyph, self.getAnchorOffsets(
                        baseGlyph, markGlyph))
                # set the advanced width
                dfltSidebearings = self.upm * .05  # 5% of UPM
                newGlyph.leftMargin = (dfltSidebearings +
                                       self.extraSidebearings[0])
                newGlyph.rightMargin = (dfltSidebearings +
                                        self.extraSidebearings[1])
                # append the assembled glyph to the list
                glyphsList.extend(self.extraGlyphsList)
                glyphsList.append(newGlyph)

            # add line break, if both input fields have content
            if baseGlyphsNamesList and markGlyphsNamesList:
                glyphsList.extend(self.extraGlyphsList)
                glyphsList.append(newLine)

        # update the contents of the MultiLineView
        self.w.lineView.set(glyphsList)

    def updateExtensionWindow(self):
        if self.calibrateMode:
            self.updateCalibrateMode()
            return

        # NOTE: CurrentGlyph() will return zero (its length),
        # so "is not None" is necessary
        if CurrentGlyph() is not None:
            self.glyph = CurrentGlyph()
            self.glyphNamesList = self.makeGlyphNamesList(self.glyph)
            self.updateListView()
            currentGlyphName = self.glyph.name

            # base glyph + accent combinations preview
            # first check if there's a cached glyph
            if currentGlyphName in self.glyphPreviewCacheDict:
                self.w.lineView.set(
                    self.glyphPreviewCacheDict[currentGlyphName])

            # assemble the glyphs
            else:
                glyphsList = []
                for glyphNameInUIList in self.glyphNamesList:
                    # trim the contextual portion of the UI glyph name
                    # and keep track of it
                    if CONTEXTUAL_ANCHOR_TAG in glyphNameInUIList:
                        cxtTagIndex = glyphNameInUIList.find(
                            CONTEXTUAL_ANCHOR_TAG)
                        glyphNameCXTportion = glyphNameInUIList[cxtTagIndex:]
                        # this line must be last!
                        glyphNameInUIList = glyphNameInUIList[:cxtTagIndex]
                    else:
                        glyphNameCXTportion = ''

                    newGlyph = RGlyph()
                    newGlyph.setParent(self.font)

                    # the glyph in the UI list is a mark
                    if glyphNameInUIList in self.marksDict:
                        markGlyph = self.font[glyphNameInUIList]

                        # append base glyph
                        newGlyph = self.deepAppendGlyph(newGlyph, self.glyph)
                        # append mark glyph
                        newGlyph = self.deepAppendGlyph(
                            newGlyph, markGlyph, self.getAnchorOffsets(
                                self.glyph, markGlyph, glyphNameCXTportion))

                        # set the advanced width
                        # combining marks or other glyphs with
                        # a small advanced width
                        if self.glyph.width < 10:
                            newGlyph.leftMargin = self.upm * .05  # 5% of UPM
                            newGlyph.rightMargin = newGlyph.leftMargin
                        else:
                            newGlyph.width = self.glyph.width

                    # the glyph in the UI list is a base
                    else:
                        baseGlyph = self.font[glyphNameInUIList]

                        # append base glyph
                        newGlyph = self.deepAppendGlyph(newGlyph, baseGlyph)
                        # append mark glyph
                        newGlyph = self.deepAppendGlyph(
                            newGlyph, self.glyph, self.getAnchorOffsets(
                                baseGlyph, self.glyph))

                        # set the advanced width
                        # combining marks or other glyphs with
                        # a small advanced width
                        if self.glyph.width < 10:
                            newGlyph.leftMargin = self.upm * .05
                            newGlyph.rightMargin = newGlyph.leftMargin
                        else:
                            newGlyph.width = baseGlyph.width

                    # pad the new glyph if it has too much overhang
                    if newGlyph.leftMargin < self.upm * .15:
                        newGlyph.leftMargin = self.upm * .05
                    if newGlyph.rightMargin < self.upm * .15:
                        newGlyph.rightMargin = self.upm * .05

                    # add extra sidebearings
                        newGlyph.leftMargin += self.extraSidebearings[0]
                        newGlyph.rightMargin += self.extraSidebearings[1]

                    # one last check for making sure the new glyph
                    # can be displayed
                    if not newGlyph.components:
                        glyphsList.extend(self.extraGlyphsList)
                        glyphsList.append(newGlyph)
                    else:
                        print("Combination with mark glyph %s can't be "
                              "previewed because it contains component %s." %
                              (glyphNameInUIList + glyphNameCXTportion,
                               newGlyph.components[0].baseGlyph))

                glyphsList.extend(self.extraGlyphsList)
                self.w.lineView.set(glyphsList)

                # add to the cache
                self.glyphPreviewCacheDict[currentGlyphName] = glyphsList
        else:
            self.w.lineView.set([])

    def listSelectionCallback(self, sender):
        selectedGlyphNamesList = []
        for index in sender.getSelection():
            selectedGlyphNamesList.append(self.glyphNamesList[index])
        self.selectedGlyphNamesList = selectedGlyphNamesList
        self.updateGlyphView()

    def updateGlyphView(self):
        UpdateCurrentGlyphView()

    def fillAnchorsAndMarksDicts(self):
        # reset all the dicts
        self.glyphPreviewCacheDict.clear()
        self.anchorsOnMarksDict.clear()
        self.anchorsOnBasesDict.clear()
        self.CXTanchorsOnBasesDict.clear()
        self.marksDict.clear()
        markGlyphsWithMoreThanOneAnchorTypeList = []

        for glyphName in self.font.glyphOrder:
            glyphAnchorsList = self.font[glyphName].anchors
            for anchor in glyphAnchorsList:
                if anchor.name[0] == '_':
                    anchorName = anchor.name[1:]
                    # add to AnchorsOnMarks dictionary
                    if anchorName not in self.anchorsOnMarksDict:
                        self.anchorsOnMarksDict[anchorName] = [glyphName]
                    else:
                        tempList = self.anchorsOnMarksDict[anchorName]
                        tempList.append(glyphName)
                        self.anchorsOnMarksDict[anchorName] = tempList
                    # add to Marks dictionary
                    if glyphName not in self.marksDict:
                        self.marksDict[glyphName] = anchorName
                    else:
                        if (glyphName not in
                                markGlyphsWithMoreThanOneAnchorTypeList):
                            markGlyphsWithMoreThanOneAnchorTypeList.append(
                                glyphName)
                else:
                    anchorName = anchor.name
                    if CONTEXTUAL_ANCHOR_TAG in anchorName:
                        # add to AnchorsOnBases dictionary
                        if anchorName not in self.CXTanchorsOnBasesDict:
                            self.CXTanchorsOnBasesDict[anchorName] = [
                                glyphName]
                        else:
                            tempList = self.CXTanchorsOnBasesDict[anchorName]
                            tempList.append(glyphName)
                            self.CXTanchorsOnBasesDict[anchorName] = tempList
                    else:
                        # add to AnchorsOnBases dictionary
                        if anchorName not in self.anchorsOnBasesDict:
                            self.anchorsOnBasesDict[anchorName] = [glyphName]
                        else:
                            tempList = self.anchorsOnBasesDict[anchorName]
                            tempList.append(glyphName)
                            self.anchorsOnBasesDict[anchorName] = tempList

        if markGlyphsWithMoreThanOneAnchorTypeList:
            for glyphName in markGlyphsWithMoreThanOneAnchorTypeList:
                print("ERROR: Glyph %s has more than one type of anchor." %
                      glyphName)

    def makeGlyphNamesList(self, glyph):
        glyphNamesList = []
        markGlyphIsAbleToBeBase = False
        # NOTE: "if glyph" will return zero (its length),
        # so "is not None" is necessary
        if glyph is not None:
            # assemble the list for the UI list
            for anchor in glyph.anchors:
                anchorName = anchor.name
                # the glyph selected is a base
                if anchorName in self.anchorsOnMarksDict:
                    glyphNamesList.extend(self.anchorsOnMarksDict[anchorName])
                # the glyph selected is a mark
                # skips the leading underscore
                elif anchorName[1:] in self.anchorsOnBasesDict:
                    glyphNamesList.extend(
                        self.anchorsOnBasesDict[anchorName[1:]])
                # the glyph selected is a base
                elif anchorName[0] != '_' and (
                        anchorName in self.CXTanchorsOnBasesDict):
                    cxtTagIndex = anchorName.find(CONTEXTUAL_ANCHOR_TAG)
                    anchorNameNOTCXTportion = anchorName[:cxtTagIndex]
                    anchorNameCXTportion = anchorName[cxtTagIndex:]
                    # XXX here only the first mark glyph that has an anchor of
                    # the kind 'anchorNameNOTCXTportion' is considered.
                    # This is probably harmless, but...
                    glyphName = '%s%s' % (
                        self.anchorsOnMarksDict[anchorNameNOTCXTportion][0],
                        anchorNameCXTportion)
                    glyphNamesList.append(glyphName)

            # for mark glyphs, test if they're able to get
            # other mark glyphs attached to them.
            # this will (correctly) prevent the UI list from including
            # glyph names that cannot be displayed with the current glyph
            if glyph.name in self.marksDict:
                for anchor in glyph.anchors:
                    # the current mark glyph has anchors that
                    # allow it to be a base for other marks
                    if anchor.name[0] != '_':
                        markGlyphIsAbleToBeBase = True
                        break
                # remove marks from the glyph list if the
                # current mark glyph can't work as a base
                if not markGlyphIsAbleToBeBase:
                    # iterate from the end of the list
                    for glyphName in glyphNamesList[::-1]:
                        if glyphName in self.marksDict:
                            glyphNamesList.remove(glyphName)
        glyphNamesList.sort()
        return glyphNamesList

    def updateListView(self):
        self.w.fontList.set(self.glyphNamesList)

    def getAnchorOffsets(self, canvasGlyph, glyphToDraw,
                         anchorNameCXTportion=''):
        # the current glyph is a mark
        if canvasGlyph.name in self.marksDict:
            # glyphToDraw is also a mark (mark-to-mark case)
            if glyphToDraw.name in self.marksDict:
                # pick the (mark glyph) anchor to draw on
                for anchor in canvasGlyph.anchors:
                    if anchor.name[0] != '_':
                        anchorName = anchor.name
                        markAnchor = anchor
                        break
                # pick the (base glyph) anchor to draw on
                for anchor in glyphToDraw.anchors:
                    try:
                        if anchor.name == '_' + anchorName:
                            baseAnchor = anchor
                            break
                    except UnboundLocalError:
                        continue
            # glyphToDraw is not a mark
            else:
                # pick the (mark glyph) anchor to draw on
                for anchor in canvasGlyph.anchors:
                    if anchor.name[0] == '_':
                        anchorName = anchor.name[1:]
                        markAnchor = anchor
                        break
                # pick the (base glyph) anchor to draw on
                for anchor in glyphToDraw.anchors:
                    try:
                        if anchor.name == anchorName:
                            baseAnchor = anchor
                            break
                    except UnboundLocalError:
                        continue

            try:
                offsetX = markAnchor.x - baseAnchor.x
                offsetY = markAnchor.y - baseAnchor.y
            except UnboundLocalError:
                offsetX = 0
                offsetY = 0

        # the current glyph is a base
        else:
            try:
                anchorName = self.marksDict[glyphToDraw.name]
            except KeyError:
                anchorName = None

            if anchorName:
                # pick the (base glyph) anchor to draw on
                for anchor in canvasGlyph.anchors:
                    if anchor.name == anchorName + anchorNameCXTportion:
                        baseAnchor = anchor
                        break
                # pick the (mark glyph) anchor to draw on
                for anchor in glyphToDraw.anchors:
                    if anchor.name == '_' + anchorName:
                        markAnchor = anchor
                        break

            try:
                offsetX = baseAnchor.x - markAnchor.x
                offsetY = baseAnchor.y - markAnchor.y
            except UnboundLocalError:
                offsetX = 0
                offsetY = 0

        return (offsetX, offsetY)

    def _drawGlyphs(self, info):
        """ draw stuff in the glyph window view """
        translateBefore = (0, 0)

        for glyphName in self.selectedGlyphNamesList:
            # trim the contextual portion of the UI glyph name
            # and keep track of it
            if CONTEXTUAL_ANCHOR_TAG in glyphName:
                cxtTagIndex = glyphName.find(CONTEXTUAL_ANCHOR_TAG)
                glyphNameCXTportion = glyphName[cxtTagIndex:]
                glyphName = glyphName[:cxtTagIndex]  # this line must be last!
            else:
                glyphNameCXTportion = ''

            glyphToDraw = self.font[glyphName]

            # determine the offset of the anchors
            offset = self.getAnchorOffsets(
                self.glyph, glyphToDraw, glyphNameCXTportion)

            # set the offset of the drawing
            translate(offset[0] - translateBefore[0],
                      offset[1] - translateBefore[1])

            # record the shift amounts (these are needed for resetting the
            # drawing position when more than one mark is selected on the list)
            translateBefore = offset

            # set the fill & stroke
            fill(0, 0, self.Blue, self.Alpha)
            strokeWidth(None)

            # draw it
            mojoPen = MojoDrawingToolsPen(glyphToDraw, self.font)
            glyphToDraw.draw(mojoPen)
            mojoPen.draw()


class MojoDrawingToolsPen(BasePen):
    def __init__(self, g, f):
        BasePen.__init__(self, None)
        self.g = g
        self.f = f
        newPath()

    def moveTo(self, pt):
        moveTo(pt)

    def lineTo(self, pt):
        lineTo(pt)

    def curveTo(self, pt1, pt2, pt3):
        curveTo(pt1, pt2, pt3)

    def closePath(self):
        closePath()

    def endPath(self):
        closePath()

    def draw(self):
        drawPath()

    def addComponent(self, baseName, transformation):
        glyph = self.f[baseName]
        tPen = TransformPen(self, transformation)
        glyph.draw(tPen)


if CurrentFont() is not None:
    AdjustAnchors()
else:
    import vanilla.dialogs
    NSBeep()
    vanilla.dialogs.message(extensionName, "Open a font first.")
