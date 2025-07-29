import os
import re

from qtpy import QtGui, QtWidgets, QtCore

from ayon_debugly.lib import ADDON_ROOT
from ayon_debugly.logger import log

class LinkableTextEdit(QtWidgets.QTextEdit):
    """Custom QTextEdit that handles link clicks"""
    
    def mousePressEvent(self, event):
        """Handle mouse press events to detect link clicks"""
        if event.button() == QtCore.Qt.LeftButton:
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QtGui.QTextCursor.WordUnderCursor)
            format = cursor.charFormat()
            if format.isAnchor():
                url = format.anchorHref()
                if url:
                    self._open_url(url)
                    return
        super().mousePressEvent(event)

    def _open_url(self, url):
        """Open URL in default browser"""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            log.debug(f"Failed to open URL {url}: {e}")
            QtWidgets.QMessageBox.warning(self, "Link Error", f"Could not open link: {url}")


def simple_markdown_to_html(text):
    # Headings (h1-h6)
    for i in range(6, 0, -1):
        pattern = r'^\s*' + '#' * i + r' (.*)$'
        text = re.sub(pattern, rf'<h{i}>\1</h{i}>', text, flags=re.MULTILINE)
    # Bold ( **text** or __text__ )
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
    # Italic ( *text* or _text_ )
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)

    # Links [text](url)
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
    # Blockquotes (> text)
    text = re.sub(r'^\s*>\s*(.*)$', r'<blockquote style="background-color: #3a3a3a; color: #cccccc; font-style: italic; padding: 10px; margin: 5px 0; border-left: 3px solid #666666;">\1</blockquote>', text, flags=re.MULTILINE)
    # Horizontal dividers (---)
    text = re.sub(r'^\s*---\s*$', r'<hr>', text, flags=re.MULTILINE)
    # Ordered lists (1. item)
    text = re.sub(r'^(\d+)\. (.*)$', r'<li>\2</li>', text, flags=re.MULTILINE)
    # Unordered lists (- item)
    text = re.sub(r'^- (.*)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    # Wrap list items in <ul> or <ol>
    def wrap_list_items(html, tag):
        lines = html.split('\n')
        in_list = False
        out = []
        for line in lines:
            if line.startswith('<li>'):
                if not in_list:
                    out.append(f'<{tag}>')
                    in_list = True
                out.append(line)
            else:
                if in_list:
                    out.append(f'</{tag}>')
                    in_list = False
                out.append(line)
        if in_list:
            out.append(f'</{tag}>')
        return '\n'.join(out)
    text = wrap_list_items(text, 'ul')
    text = wrap_list_items(text, 'ol')
    # Paragraphs: replace remaining newlines with <br>, but not after block tags
    # This avoids look-behind by splitting and joining
    lines = text.split('\n')
    safe_lines = []
    block_tags = ("</h1>", "</h2>", "</h3>", "</h4>", "</h5>", "</h6>", "</ul>", "</ol>", "</li>", "</p>")
    for i, line in enumerate(lines):
        if line.strip() == "":
            if i > 0 and not any(lines[i-1].endswith(tag) for tag in block_tags):
                safe_lines.append("<br>")
            else:
                safe_lines.append("")
        else:
            safe_lines.append(line)
    text = '\n'.join(safe_lines)
    return text

class WysiwygWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_font()
        self._setup_ui()
        self._connect_signals()

    def _setup_font(self):
        # Load FontAwesome 7 Free Solid font
        font_path = os.path.join(ADDON_ROOT, "vendor", "fontawesome", "FontAwesome7Free-Solid-900.otf")
        log.debug(f"Looking for FontAwesome 7 at: {font_path}")
        log.debug(f"Font file exists: {os.path.exists(font_path)}")
        
        self.fontawesome_family = None
        
        if os.path.exists(font_path):
            font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
            log.debug(f"Font ID: {font_id}")
            if font_id != -1:
                font_families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                log.debug(f"Available font families: {font_families}")
                if font_families:
                    self.fontawesome_family = font_families[0]
                    log.debug(f"Successfully loaded FontAwesome 7: {self.fontawesome_family}")
                    
                    # Test if the font is working by creating a test font
                    test_font = QtGui.QFont()
                    test_font.setFamily(self.fontawesome_family)
                    test_font.setPointSize(12)
                    test_font.setWeight(QtGui.QFont.Black)
                    log.debug(f"Test font family: {test_font.family()}, weight: {test_font.weight()}")
                    
                else:
                    log.debug("No font families found")
            else:
                log.debug("Failed to load font")
        else:
            log.debug(f"Font file not found at {font_path}")

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        
        # Toolbar with all markdown features
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # Single rich text editor (WYSIWYG)
        self.editor = LinkableTextEdit()
        self.editor.setMinimumHeight(200)
        self.editor.setStyleSheet("""
            QTextEdit {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 8px;
                color: #E0E0E0;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 12px;
                line-height: 1.4;
            }
            QTextEdit:focus {
                border-color: #888888;
                background-color: #3D3D3D;
            }
        """)
        
        # Set larger default font
        font = self.editor.font()
        font.setPointSize(12)
        self.editor.setFont(font)
        
        # Set template text as rendered HTML
        template_markdown = """
# Problem
---
   
**Context & description:** Explain what you were trying to accomplish when the bug occurred

   
# Expected behavior
---
   
**Expected vs. actual behavior:** Clearly distinguish between what you expected to happen and what actually happened.
   
   
   
# How to reproduce
---
**Step-by-step reproduction:** List the exact steps someone else would need to follow to encounter the same issue

   
   
"""
        template_html = simple_markdown_to_html(template_markdown)
        log.debug(f"Template HTML: {template_html}")
        self.editor.setHtml(template_html)
        layout.addWidget(self.editor)

    def _create_toolbar(self):
        toolbar = QtWidgets.QWidget()
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setSpacing(4)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        
        # FontAwesome 7 Free Solid unicode codes - corrected
        try:
            if self.fontawesome_family:
                log.debug("Using FontAwesome 7 icons")
                # FontAwesome 7 unicode characters (corrected codes)
                self.bold_btn = self._create_text_button("B", "Bold", bold=True)
                self.italic_btn = self._create_text_button("I", "Italic", italic=True)
                self.underline_btn = self._create_text_button("U", "Underline", underline=True)
                self.strikethrough_btn = self._create_text_button("S", "Strikethrough", strikeout=True)
                
                # Headings - using different icons for each level
                self.h1_btn = self._create_text_button("H1", "Heading 1")
                self.h2_btn = self._create_text_button("H2", "Heading 2")
                self.h3_btn = self._create_text_button("H3", "Heading 3")
                
                # Lists - using FontAwesome icons
                self.bullet_btn = self._create_icon_button("\uf0ca", "Bullet List")  # fa-list-ul
                self.number_btn = self._create_icon_button("\uf0cb", "Numbered List")  # fa-list-ol
                
                # Link only
                self.link_btn = self._create_icon_button("\uf0c1", "Link")  # fa-link
            else:
                raise Exception("FontAwesome family not loaded")
        except Exception as e:
            log.debug(f"FontAwesome not loaded or failed: {e}, using text fallbacks")
            # Simple text fallbacks
            self.bold_btn = self._create_text_button("B", "Bold", bold=True)
            self.italic_btn = self._create_text_button("I", "Italic", italic=True)
            self.underline_btn = self._create_text_button("U", "Underline", underline=True)
            self.strikethrough_btn = self._create_text_button("S", "Strikethrough", strikeout=True)
            self.h1_btn = self._create_text_button("H1", "Heading 1")
            self.h2_btn = self._create_text_button("H2", "Heading 2")
            self.h3_btn = self._create_text_button("H3", "Heading 3")
            self.bullet_btn = self._create_text_button("•", "Bullet List")
            self.number_btn = self._create_text_button("1.", "Numbered List")
            self.link_btn = self._create_text_button("🔗", "Link")
        
        # Add buttons to layout
        buttons = [
            self.bold_btn, self.italic_btn, self.underline_btn, self.strikethrough_btn,
            None,  # Separator
            self.h1_btn, self.h2_btn, self.h3_btn,
            None,  # Separator
            self.bullet_btn, self.number_btn,
            None,  # Separator
            self.link_btn
        ]
        
        for btn in buttons:
            if btn is None:
                separator = QtWidgets.QFrame()
                separator.setFrameShape(QtWidgets.QFrame.VLine)
                separator.setFrameShadow(QtWidgets.QFrame.Sunken)
                separator.setMaximumHeight(24)
                separator.setStyleSheet("QFrame { color: #666666; }")
                toolbar_layout.addWidget(separator)
            else:
                toolbar_layout.addWidget(btn)
        
        toolbar_layout.addStretch()
        return toolbar

    def _create_icon_button(self, icon_unicode, tooltip):
        btn = QtWidgets.QPushButton(icon_unicode)
        
        # Create font specifically for FontAwesome 7 Free Solid
        font = QtGui.QFont()
        font.setFamily(self.fontawesome_family)
        font.setPointSize(10)
        # FontAwesome 7 Free Solid requires weight 900 (Black)
        font.setWeight(QtGui.QFont.Black)
        font.setStyleStrategy(QtGui.QFont.PreferAntialias)
        
        btn.setFont(font)
        btn.setToolTip(tooltip)
        btn.setFixedSize(28, 28)
        
        # Apply neutral dark theme styling
        btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                color: #E0E0E0;
                padding: 2px;
                font-family: inherit;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #888888;
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
                border-color: #555555;
            }
        """)
        
        # Debug output
        log.debug(f"Created button '{tooltip}': family='{font.family()}', weight={font.weight()}")
        log.debug(f"Button font family: '{btn.font().family()}'")
        
        return btn

    def _create_text_button(self, text, tooltip, bold=False, italic=False, underline=False, strikeout=False):
        btn = QtWidgets.QPushButton(text)
        
        # Create styled font for text fallbacks
        font = QtGui.QFont("Segoe UI", 9)
        if bold:
            font.setBold(True)
        if italic:
            font.setItalic(True)
        if underline:
            font.setUnderline(True)
        if strikeout:
            font.setStrikeOut(True)
        
        btn.setFont(font)
        btn.setToolTip(tooltip)
        btn.setFixedSize(32, 28)
        
        # Apply neutral dark theme styling
        btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                color: #E0E0E0;
                padding: 2px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #888888;
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
                border-color: #555555;
            }
        """)
        
        return btn

    def _connect_signals(self):
        self.bold_btn.clicked.connect(lambda: self._toggle_format(QtGui.QTextCharFormat.FontWeight, QtGui.QFont.Bold))
        self.italic_btn.clicked.connect(lambda: self._toggle_format(QtGui.QTextCharFormat.FontItalic, True))
        self.underline_btn.clicked.connect(lambda: self._toggle_format(QtGui.QTextCharFormat.TextUnderlineStyle, QtGui.QTextCharFormat.SingleUnderline))
        self.strikethrough_btn.clicked.connect(lambda: self._toggle_format(QtGui.QTextCharFormat.FontStrikeOut, True))
        
        self.h1_btn.clicked.connect(lambda: self._apply_heading(1))
        self.h2_btn.clicked.connect(lambda: self._apply_heading(2))
        self.h3_btn.clicked.connect(lambda: self._apply_heading(3))
        
        self.bullet_btn.clicked.connect(lambda: self._insert_list(QtGui.QTextListFormat.ListDisc))
        self.number_btn.clicked.connect(lambda: self._insert_list(QtGui.QTextListFormat.ListDecimal))
        
        self.link_btn.clicked.connect(self._insert_link)

    def _toggle_format(self, property_type, value):
        cursor = self.editor.textCursor()
        
        if cursor.hasSelection():
            # For selections, we need to check if the entire selection has the same format
            # and then apply the opposite format
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            
            # Check if the entire selection has the same format
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
            
            # Get the format at the start of selection
            start_format = cursor.charFormat()
            
            # Check if the entire selection has the same format
            all_same = True
            if property_type == QtGui.QTextCharFormat.FontWeight:
                target_weight = start_format.fontWeight()
                for pos in range(start_pos, end_pos):
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + 1, QtGui.QTextCursor.KeepAnchor)
                    if cursor.charFormat().fontWeight() != target_weight:
                        all_same = False
                        break
                is_bold = target_weight == QtGui.QFont.Bold
            elif property_type == QtGui.QTextCharFormat.FontItalic:
                target_italic = start_format.fontItalic()
                for pos in range(start_pos, end_pos):
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + 1, QtGui.QTextCursor.KeepAnchor)
                    if cursor.charFormat().fontItalic() != target_italic:
                        all_same = False
                        break
                is_italic = target_italic
            elif property_type == QtGui.QTextCharFormat.TextUnderlineStyle:
                target_underline = start_format.underlineStyle()
                for pos in range(start_pos, end_pos):
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + 1, QtGui.QTextCursor.KeepAnchor)
                    if cursor.charFormat().underlineStyle() != target_underline:
                        all_same = False
                        break
                is_underlined = target_underline != QtGui.QTextCharFormat.NoUnderline
            elif property_type == QtGui.QTextCharFormat.FontStrikeOut:
                target_strike = start_format.fontStrikeOut()
                for pos in range(start_pos, end_pos):
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + 1, QtGui.QTextCursor.KeepAnchor)
                    if cursor.charFormat().fontStrikeOut() != target_strike:
                        all_same = False
                        break
                is_strikethrough = target_strike
            
            # Restore selection
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
            
            # Create format to apply
            toggle_format = QtGui.QTextCharFormat()
            
            if property_type == QtGui.QTextCharFormat.FontWeight:
                if all_same and is_bold:
                    toggle_format.setFontWeight(QtGui.QFont.Normal)
                else:
                    toggle_format.setFontWeight(QtGui.QFont.Bold)
            elif property_type == QtGui.QTextCharFormat.FontItalic:
                if all_same and is_italic:
                    toggle_format.setFontItalic(False)
                else:
                    toggle_format.setFontItalic(True)
            elif property_type == QtGui.QTextCharFormat.TextUnderlineStyle:
                if all_same and is_underlined:
                    toggle_format.setUnderlineStyle(QtGui.QTextCharFormat.NoUnderline)
                else:
                    toggle_format.setUnderlineStyle(QtGui.QTextCharFormat.SingleUnderline)
            elif property_type == QtGui.QTextCharFormat.FontStrikeOut:
                if all_same and is_strikethrough:
                    toggle_format.setFontStrikeOut(False)
                else:
                    toggle_format.setFontStrikeOut(True)
            
            # Apply the format
            cursor.mergeCharFormat(toggle_format)
        else:
            # No selection - apply to current position and future typing
            current_format = cursor.charFormat()
            toggle_format = QtGui.QTextCharFormat()
            
            if property_type == QtGui.QTextCharFormat.FontWeight:
                is_bold = current_format.fontWeight() == QtGui.QFont.Bold
                toggle_format.setFontWeight(QtGui.QFont.Normal if is_bold else QtGui.QFont.Bold)
            elif property_type == QtGui.QTextCharFormat.FontItalic:
                is_italic = current_format.fontItalic()
                toggle_format.setFontItalic(not is_italic)
            elif property_type == QtGui.QTextCharFormat.TextUnderlineStyle:
                is_underlined = current_format.underlineStyle() != QtGui.QTextCharFormat.NoUnderline
                toggle_format.setUnderlineStyle(QtGui.QTextCharFormat.NoUnderline if is_underlined else QtGui.QTextCharFormat.SingleUnderline)
            elif property_type == QtGui.QTextCharFormat.FontStrikeOut:
                is_strikethrough = current_format.fontStrikeOut()
                toggle_format.setFontStrikeOut(not is_strikethrough)
            
            cursor.mergeCharFormat(toggle_format)

    def _apply_heading(self, level):
        cursor = self.editor.textCursor()
        cursor.select(QtGui.QTextCursor.BlockUnderCursor)
        
        format = QtGui.QTextCharFormat()
        format.setFontWeight(QtGui.QFont.Bold)
        format.setFontPointSize(18 - level * 2)  # H1=16, H2=14, H3=12
        
        cursor.setCharFormat(format)

    def _insert_list(self, list_type):
        cursor = self.editor.textCursor()
        
        if cursor.hasSelection():
            # Check if the selection is already a list of the same type
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            
            # Check if the entire selection is already a list of the same type
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
            
            # Get the block format at the start
            start_block = cursor.block()
            start_list = start_block.textList()
            
            # Check if all blocks in selection are lists of the same type
            all_same_list = True
            if start_list:
                target_style = start_list.format().style()
                for pos in range(start_pos, end_pos):
                    cursor.setPosition(pos)
                    block = cursor.block()
                    list_obj = block.textList()
                    if not list_obj or list_obj.format().style() != target_style:
                        all_same_list = False
                        break
            else:
                all_same_list = False
            
            # Restore selection
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
            
            if all_same_list and start_list and start_list.format().style() == list_type:
                # Remove list formatting
                cursor.setPosition(start_pos)
                cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
                
                # Convert list items back to normal text
                selected_text = cursor.selectedText()
                lines = selected_text.split('\n')
                
                cursor.removeSelectedText()
                
                # Insert as normal text
                for i, line in enumerate(lines):
                    if i > 0:
                        cursor.insertBlock()
                    cursor.insertText(line.strip())
            else:
                # Convert selected text to list items
                selected_text = cursor.selectedText()
                lines = selected_text.split('\n')
                
                # Remove the selection and insert list
                cursor.removeSelectedText()
                
                list_format = QtGui.QTextListFormat()
                list_format.setStyle(list_type)
                cursor.insertList(list_format)
                
                # Insert each line as a list item
                for i, line in enumerate(lines):
                    if line.strip():  # Only add non-empty lines
                        if i > 0:
                            cursor.insertBlock()  # New line for each item
                        cursor.insertText(line.strip())
        else:
            # No selection - check if current block is already a list of the same type
            current_block = cursor.block()
            current_list = current_block.textList()
            
            if current_list and current_list.format().style() == list_type:
                # Remove list formatting from current block
                cursor.setPosition(current_block.position())
                cursor.setPosition(current_block.position() + current_block.length() - 1, QtGui.QTextCursor.KeepAnchor)
                cursor.setBlockFormat(QtGui.QTextBlockFormat())
            else:
                # Insert a new list
                list_format = QtGui.QTextListFormat()
                list_format.setStyle(list_type)
                cursor.insertList(list_format)

    def _insert_link(self):
        cursor = self.editor.textCursor()
        selected = cursor.selectedText() or "link text"
        url, ok = QtWidgets.QInputDialog.getText(self, "Insert Link", "URL:")
        
        if ok and url:
            format = QtGui.QTextCharFormat()
            format.setAnchor(True)
            format.setAnchorHref(url)
            format.setForeground(QtGui.QColor("#E0E0E0"))
            format.setUnderlineStyle(QtGui.QTextCharFormat.SingleUnderline)
            
            cursor.insertText(selected, format)

    def toHtml(self):
        return self.editor.toHtml()

    def toMarkdown(self):
        # Convert rich text back to markdown for storage
        return self._html_to_markdown(self.editor.toHtml())

    def _html_to_markdown(self, html):
        # Basic HTML to Markdown conversion
        # This is a simplified version - you might want to use a proper library
        text = html
        text = re.sub(r'<b>(.*?)</b>', r'**\1**', text)
        text = re.sub(r'<i>(.*?)</i>', r'*\1*', text)
        text = re.sub(r'<a href="(.*?)">(.*?)</a>', r'[\2](\1)', text)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        return text.strip() 
