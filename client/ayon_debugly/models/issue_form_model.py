class IssueFormModel:
    def __init__(self):
        self.title = ""
        self.message = ""
        self.selected_logs = []
        self.screenshot_path = None
        self.attachments = []

    def is_valid(self):
        return bool(self.title and (self.message or self.attachments)) 