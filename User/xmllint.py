import sublime_plugin

class FormatXml(sublime_plugin.TextCommand):
    def is_enabled(self):
        return self.view.settings().get('syntax') == "Packages/XML/XML.tmLanguage"

    def run(self, edit):
        self.view.run_command('filter_through_command',
                              {"cmdline": "xmllint --format -"})