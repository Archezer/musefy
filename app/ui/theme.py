from __future__ import annotations

# A deliberately neutral "smoked glass" system: it stays legible on Windows
# without borrowing Spotify's green or the usual blue desktop-app accents.
DARK_THEME = """
* {
    font-family: "Segoe UI", Arial, sans-serif;
    color: #ECECEE;
}
QMainWindow, QWidget#appRoot {
    background-color: #07090B;
}
QWidget#contentOverlay, QWidget#mapLayer, QSplitter {
    background: transparent;
}
QFrame#glassPanel, QFrame#playerBar, QFrame#topBar,
QFrame#playlistStrip, QFrame#graphStage {
    background-color: rgba(27, 29, 33, 166);
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 15px;
}
QFrame#sidebar {
    background: transparent;
    border: none;
    border-radius: 0;
}
QFrame#sidebarSeparator {
    color: rgba(255, 255, 255, 24);
    background-color: rgba(255, 255, 255, 24);
    max-height: 1px;
}
QFrame#graphStage {
    background-color: rgba(30, 31, 34, 238);
}
QFrame#playlistStrip {
    background-color: transparent;
    border: none;
}
QFrame#glassPanel {
    background-color: transparent;
    border: none;
    border-radius: 0;
}
QFrame#libraryPanel, QFrame#queuePanel {
    background: #111416;
    border: none;
    border-radius: 15px;
}
QFrame#libraryPanel[liquidGlass="true"], QFrame#queuePanel[liquidGlass="true"] {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(17, 20, 22, 0),
        stop: .28 rgba(17, 20, 22, 88),
        stop: .5 rgba(17, 20, 22, 236),
        stop: .56 rgba(17, 20, 22, 255),
        stop: 1 rgba(17, 20, 22, 255)
    );
    border: none;
    border-radius: 15px;
}
QFrame#playerBar {
    background-color: #0D1012;
    border-color: rgba(255, 255, 255, 18);
}
QFrame#librarySearch {
    background-color: rgba(31, 34, 37, 242);
    border: 1px solid rgba(255, 255, 255, 34);
    border-radius: 19px;
}
QFrame#librarySearch:hover {
    border-color: rgba(181, 251, 224, 92);
}
QLineEdit#librarySearchInput {
    background: transparent;
    border: none;
    padding: 0;
    color: #F2F4F3;
    selection-background-color: #4D9F8A;
    selection-color: #07100F;
    font-size: 13px;
}
QLineEdit#librarySearchInput:focus {
    border: none;
}
QLineEdit#librarySearchInput::placeholder {
    color: #94979B;
}
QToolButton#librarySearchClear {
    background: transparent;
    border: none;
    padding: 2px;
    border-radius: 13px;
}
QToolButton#librarySearchClear:hover {
    background-color: rgba(255, 255, 255, 22);
}
QDialog {
    background-color: #111416;
    border: 1px solid rgba(181, 251, 224, 42);
    border-radius: 0;
}
QDialog QLabel {
    background: transparent;
}
QFrame#listeningTotal {
    background-color: rgba(255, 255, 255, 8);
    border: 1px solid rgba(181, 251, 224, 42);
    border-radius: 13px;
}
QLabel#listeningTotalHeading {
    color: #B5FBE0;
    font-size: 11px;
    font-weight: 700;
}
QLabel#listeningTotalValue {
    color: #F1F9F5;
    font-size: 19px;
    font-weight: 700;
}
QLabel#listeningTotalCaption {
    color: #8F9A98;
    font-size: 10px;
}
QFrame#listeningTotalDivider {
    background-color: rgba(181, 251, 224, 34);
    border: none;
    max-width: 1px;
}
QFrame#listeningGraphPanel, QFrame#listeningDiagramPanel,
QFrame#listeningDetailPanel {
    background-color: rgba(8, 11, 13, 112);
    border: 1px solid rgba(181, 251, 224, 24);
    border-radius: 11px;
}
QLabel#listeningPanelHeading {
    color: #B5FBE0;
    font-size: 11px;
    font-weight: 700;
}
QLabel#listeningDetailInsight {
    color: #A9D8C9;
    font-size: 10px;
    font-weight: 600;
}
QLabel#searchElapsedTime {
    color: #899692;
    font-size: 11px;
    font-variant: small-caps;
    padding-left: 12px;
}
QDialog QLineEdit {
    background-color: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 28);
    border-radius: 9px;
    padding: 7px 9px;
    selection-background-color: #4D9F8A;
    selection-color: #07100F;
}
QDialog QLineEdit:focus {
    border-color: rgba(181, 251, 224, 112);
}
QDialog QListWidget {
    background-color: rgba(8, 11, 13, 165);
    border-color: rgba(181, 251, 224, 34);
    border-radius: 12px;
}
QProgressBar#searchProgressBar {
    background-color: rgba(255, 255, 255, 12);
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}
QProgressBar#searchProgressBar::chunk {
    background-color: #5DD8B7;
    border-radius: 3px;
}
QLabel#searchElapsedTime {
    color: #8F9A98;
    font-size: 11px;
    min-width: 42px;
}
QFrame#spotifySyncRow, QFrame#spotifySettingsSection {
    background-color: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 22);
    border-radius: 11px;
}
QDialog#spotifySettingsDialog {
    background-color: #111416;
}
QFrame#spotifySyncRow:hover, QFrame#spotifySettingsSection:hover {
    background-color: rgba(112, 224, 190, 10);
    border-color: rgba(181, 251, 224, 62);
}
QLabel#spotifySyncTitle, QLabel#spotifySettingsTitle {
    color: #F1F5F3;
    font-weight: 700;
}
QLabel#spotifySyncSubtitle, QLabel#spotifySettingsDescription {
    color: #999FA1;
    font-size: 11px;
}
QLabel#spotifyAuthStatus[connected="true"],
QLabel#spotifySettingsAuthStatus[connected="true"] {
    color: #B5FBE0;
    font-weight: 700;
}
QLabel#spotifyAuthStatus[connected="false"],
QLabel#spotifySettingsAuthStatus[connected="false"] {
    color: #9EA5A4;
}
QLabel#spotifySyncArrow {
    color: #8ACAB5;
    font-size: 22px;
    font-weight: 600;
}
QLabel#spotifySettingsStatus {
    color: #AEB8B4;
    font-size: 11px;
}
QCheckBox#spotifyFavSyncCheck {
    spacing: 7px;
    color: #E9EFEC;
    font-weight: 650;
}
QCheckBox#spotifyFavSyncCheck::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid rgba(181, 251, 224, 92);
    border-radius: 5px;
    background: rgba(255, 255, 255, 12);
}
QCheckBox#spotifyFavSyncCheck::indicator:hover {
    border-color: #B5FBE0;
    background: rgba(112, 224, 190, 20);
}
QCheckBox#spotifyFavSyncCheck::indicator:checked {
    border-color: #B5FBE0;
    background: #4D9F8A;
}
QPushButton#spotifyOAuthButton, QPushButton#spotifySyncLastButton {
    background-color: rgba(112, 224, 190, 18);
    border-color: rgba(181, 251, 224, 66);
    color: #C9FBE9;
    font-weight: 650;
}
QPushButton#spotifyOAuthButton:hover, QPushButton#spotifySyncLastButton:hover {
    background-color: rgba(112, 224, 190, 32);
    border-color: #B5FBE0;
}
QLabel#appTitle {
    font-size: 18px;
    font-weight: 650;
    color: #F7F7F8;
}
QLabel#sectionCaption {
    color: #AFAFB5;
    font-size: 11px;
    font-weight: 650;
}
QLabel#playlistSectionTitle {
    color: #E2E8E5;
    font-size: 12px;
    font-weight: 700;
}
QLabel#appSubtitle, QLabel#playerArtist, QLabel#playlistCardName {
    color: #A3A3AA;
}
QLabel#playerTitle {
    color: #F4F4F5;
    font-weight: 650;
}
QLabel#trackCellTitle {
    color: #EEEEF0;
    font-size: 13px;
    font-weight: 600;
}
QLabel#trackCellArtist {
    color: #96969E;
    font-size: 12px;
}
QTableWidget#libraryTable {
    font-size: 12px;
}
QWidget#trackRowCell[rowState="hover"] {
    background-color: rgba(255, 255, 255, 18);
}
QWidget#trackRowCell[rowState="selected"] {
    background-color: #303334;
}
QToolButton#playlistRemoveButton {
    background: transparent;
    border: none;
    color: #9AA8A3;
    font-size: 18px;
    font-weight: 500;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
}
QToolButton#playlistRemoveButton:hover {
    background: rgba(224, 112, 128, 32);
    color: #FFB0B8;
    border-radius: 15px;
}
QToolButton#playlistRemoveButton:pressed {
    background: rgba(224, 112, 128, 52);
    color: #FFD5D9;
    border-radius: 15px;
}
QPushButton, QComboBox {
    background-color: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 9px;
    padding: 5px 9px;
    color: #E8E8EB;
}
QPushButton:hover, QComboBox:hover {
    background-color: rgba(255, 255, 255, 20);
    border-color: rgba(255, 255, 255, 54);
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 31);
}
QToolButton#railButton, QToolButton#mapCycleButton {
    background: transparent;
    border: none;
    /* QToolButton aligns the large glyph by its font line box; a little
       bottom padding lifts the visible arrow to the optical center. */
    padding: 0 0 5px 0;
}
QFrame#sidebar QToolButton#railButton:hover,
QFrame#sidebar QToolButton#mapCycleButton:hover {
    background: rgba(112, 224, 190, 12);
    border: none;
    border-radius: 21px;
}
QToolButton#plainActionButton {
    background: transparent;
    border: none;
    padding: 0;
    min-width: 0;
    min-height: 0;
}
QToolButton#plainActionButton:hover {
    background: rgba(112, 224, 190, 25);
    border: none;
    border-radius: 22px;
}
QToolButton#plainActionButton[topMenu="true"] {
    background: transparent;
    border: none;
    border-radius: 16px;
    color: #B5FBE0;
    min-width: 32px;
    min-height: 32px;
    max-width: 32px;
    max-height: 32px;
    padding: 0;
}
/* Instant-popup buttons keep a separate menu subcontrol.  Collapse it so
   the visible top-right action remains one consistently round surface. */
QToolButton#plainActionButton[topMenu="true"]::menu-button {
    width: 0px;
    background: transparent;
    border: none;
}
QToolButton#plainActionButton[topMenu="true"]:hover {
    background: transparent;
    border: none;
    border-radius: 16px;
}
QToolButton#plainActionButton[topMenu="true"]:pressed {
    background: transparent;
    border: none;
    border-radius: 16px;
}
QToolButton#auxiliaryMinimizedButton {
    background: rgba(24, 57, 54, 210);
    border: 1px solid rgba(181, 251, 224, 74);
    border-radius: 13px;
    color: #B5FBE0;
    padding: 4px 10px;
    min-height: 26px;
    max-height: 30px;
    font-size: 12px;
}
QToolButton#auxiliaryMinimizedButton:hover {
    background: rgba(74, 141, 119, 220);
    border-color: rgba(181, 251, 224, 145);
    color: #F1FFF8;
}
QToolButton#auxiliaryMinimizedButton:pressed {
    background: rgba(112, 197, 171, 230);
    color: #07100F;
}
QToolButton#plainActionButton:pressed {
    background: rgba(112, 224, 190, 42);
    border: none;
    border-radius: 22px;
}
QToolButton#playlistScrollButton {
    background: rgba(36, 53, 55, 205);
    border: none;
    border-radius: 13px;
    color: #B5FBE0;
    font-size: 30px;
    font-weight: 600;
    padding: 0;
}
QToolButton#playlistScrollButton:hover {
    background: rgba(82, 150, 132, 218);
    border: none;
    color: #F1FFF8;
}
QToolButton#playlistScrollButton:pressed {
    background: rgba(112, 197, 171, 230);
    border: none;
}
QToolButton::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
QComboBox::drop-down {
    border: none;
    width: 0px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QPushButton:disabled {
    color: #74747B;
    background-color: rgba(255, 255, 255, 5);
}
QComboBox QAbstractItemView {
    background-color: #26262A;
    border: 1px solid rgba(255, 255, 255, 38);
    selection-background-color: rgba(255, 255, 255, 24);
}
QTableWidget, QListWidget {
    background-color: rgba(10, 12, 15, 220);
    border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 11px;
    outline: none;
    padding: 3px;
}
QTableWidget#libraryTable {
    background: transparent;
    border: none;
    border-radius: 0;
    selection-background-color: #303334;
    selection-color: #F2F4F3;
}
QListWidget#queueList {
    background: transparent;
    border: none;
    border-radius: 0;
    selection-background-color: #252B2B;
    selection-color: #F2F4F3;
}
QTableWidget QHeaderView, QHeaderView,
QTableCornerButton::section {
    background: transparent;
}
QTableWidget#libraryTable QHeaderView::section {
    background: transparent;
}
QTableWidget#libraryTable QHeaderView::section:hover {
    background: transparent;
    color: #F3F5F4;
    font-weight: 700;
}
QTableWidget::item, QListWidget::item {
    padding: 5px 7px;
    border-radius: 0;
}
QTableWidget#libraryTable::item {
    padding-left: 4px;
}
QTableWidget::item {
    border-top: 1px solid #080A0C;
    border-left: none;
    border-right: none;
    border-bottom: none;
}
QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 8);
}
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #303334;
    color: #F2F4F3;
    outline: none;
    border-left: none;
    border-right: none;
}
QLabel#listeningSectionHeading {
    color: #B5FBE0;
    font-size: 11px;
    font-weight: 700;
}
QTableWidget#listeningHighlightsTable {
    background-color: rgba(8, 11, 13, 150);
    border: 1px solid rgba(181, 251, 224, 22);
    border-radius: 10px;
    gridline-color: transparent;
    padding: 0;
    selection-background-color: rgba(181, 251, 224, 18);
    selection-color: #F1F9F5;
}
QTableWidget#listeningHighlightsTable QHeaderView::section {
    background-color: rgba(255, 255, 255, 8);
    color: #9FADA8;
    border-bottom: 1px solid rgba(181, 251, 224, 24);
    padding: 5px 7px;
}
QTableWidget#listeningHighlightsTable::item {
    padding: 4px 7px;
    border-bottom: 1px solid rgba(255, 255, 255, 11);
}
QTableWidget#listeningHighlightsTable::item:alternate {
    background-color: rgba(255, 255, 255, 4);
}
QTableWidget#listeningPeriodTable {
    background-color: rgba(8, 11, 13, 150);
    border: none;
    border-radius: 0;
    gridline-color: transparent;
    padding: 0;
    selection-background-color: rgba(181, 251, 224, 18);
    selection-color: #F1F9F5;
}
QTableWidget#listeningPeriodTable QHeaderView::section {
    background-color: rgba(255, 255, 255, 8);
    color: #9FADA8;
    border-bottom: 1px solid rgba(181, 251, 224, 24);
    padding: 5px 7px;
}
QTableWidget#listeningPeriodTable::item {
    padding: 4px 7px;
    border-bottom: 1px solid rgba(255, 255, 255, 11);
}
QTableWidget#listeningPeriodTable::item:alternate {
    background-color: rgba(255, 255, 255, 4);
}
QHeaderView::section {
    background-color: #171A1D;
    color: #A9A9B0;
    border: none;
    padding: 7px;
}
QHeaderView::section:first {
    padding: 7px 5px 7px 5px;
}
QSplitter::handle:horizontal {
    width: 1px;
    background-color: #080A0C;
}
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 25);
    border-radius: 11px;
    background-color: rgba(31, 31, 35, 214);
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #9999A1;
    padding: 8px 12px;
}
QTabBar::tab:selected {
    color: #F4F4F5;
    border-bottom: 2px solid #D6D6DA;
}
QSlider::groove:horizontal {
    background: #292F30;
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #B5FBE0,
        stop: .5 #5DD8B7,
        stop: 1 #32877C
    );
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #8BEBCB;
    border: 2px solid #D0FFED;
    width: 11px;
    height: 11px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider#volumeSlider::groove:horizontal {
    height: 3px;
    background: #242A2B;
}
QSlider#volumeSlider::handle:horizontal {
    width: 10px;
    height: 10px;
    margin: -5px 0;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    border: none;
    width: 12px;
    margin: 5px 2px;
}
QScrollBar:horizontal {
    background: transparent;
    border: none;
    height: 12px;
    margin: 2px 5px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(116, 148, 143, 180),
        stop: .5 rgba(151, 205, 188, 220),
        stop: 1 rgba(92, 133, 126, 180)
    );
    border: none;
    border-radius: 6px;
    min-height: 44px;
    min-width: 44px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(140, 190, 177, 210),
        stop: .5 rgba(188, 240, 220, 235),
        stop: 1 rgba(111, 165, 153, 210)
    );
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    height: 0px;
}
QTableWidget#libraryTable QScrollBar:vertical {
    background: transparent;
    width: 14px;
    margin: 8px 1px 8px 0;
}
QTableWidget#libraryTable QScrollBar::handle:vertical {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(93, 151, 137, 160),
        stop: .5 rgba(139, 235, 203, 205),
        stop: 1 rgba(69, 119, 110, 160)
    );
    border: none;
    min-height: 44px;
    border-radius: 7px;
}
QTableWidget#libraryTable QScrollBar::handle:vertical:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(115, 188, 169, 190),
        stop: .5 rgba(176, 247, 220, 225),
        stop: 1 rgba(84, 150, 135, 190)
    );
}
QTableWidget#libraryTable QScrollBar::add-page:vertical,
QTableWidget#libraryTable QScrollBar::sub-page:vertical {
    background: transparent;
}
QFrame#playlistCard {
    background: transparent;
    border: none;
    border-radius: 12px;
}
QMenu {
    background-color: #29292D;
    border: 1px solid rgba(255, 255, 255, 42);
    border-radius: 10px;
    padding: 5px;
}
QMenu::item {
    padding: 7px 24px 7px 11px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: rgba(255, 255, 255, 17);
}
QStatusBar {
    background-color: #07090B;
    color: #92929A;
}
"""
