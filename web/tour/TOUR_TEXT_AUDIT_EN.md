[Русский](TOUR_TEXT_AUDIT_RU.md) · **English**

# Tour text review — stage 17

All 35 tour steps were reviewed. The goal of this stage was not to change the tour mechanics but to bring the texts to a single style for a 3D farm operator.

## Common terminology

| Term | Usage |
|---|---|
| print file | a ready g-code / 3MF that can be sent to a printer |
| model | an STL / STEP or other file that still needs to be sliced |
| plate | a set of parts inside one print file |
| On plate | how many of a given part are printed by one file |
| Needed | the required number of parts |
| Printed | the accepted finished quantity |
| reprint | printing a part again after a defect / rework |
| Quick Tasks | interface section name, left untranslated |

## What changed in the texts

- Long cards were shortened; the details were kept in the "Details" block.
- The terms "file", "model", "print file" and "plate" were separated by meaning.
- The project block was rewritten in production terms: order / batch, counters, plate, Label Objects, reprint.
- Quick Tasks is described as a quick launch of individual files without creating a project.
- The diagnostics and access texts became shorter and clearer for the operator.

## Review table

| No. | step id | title | status | comment |
|---:|---|---|---|---|
| 1 | `welcome` | Welcome | rewritten | Clarified that only temporary demo data is used. |
| 2 | `connection-sync` | Connection and sync | rewritten | Simplified the explanation of the connection and autosave. |
| 3 | `language` | Interface language | rewritten | Focus on the RU/EN buttons without extra elements. |
| 4 | `settings-open` | Settings | rewritten | The list of settings sections now matches what they actually do. |
| 5 | `settings-edition` | Interface mode | rewritten | The choice is called the interface mode: it only changes the set of visible sections; all program features are free. |
| 6 | `settings-appearance` | Appearance | rewritten | Added the point for the operator: readability on the shop floor. |
| 7 | `settings-dates` | Dates and deadlines | rewritten | The term "deadlines" was replaced with "dates and deadlines". |
| 8 | `settings-slicer` | Default slicer | rewritten | Separated the notions of a model and print preparation. |
| 9 | `settings-tools` | Tools and diagnostics | rewritten | Diagnostics is described as a service tool. |
| 10 | `diagnostics-demo` | Diagnostics | rewritten | Clarified that the log does not send commands to printers. |
| 11 | `settings-access-roles-audit` | Access, roles and audit | rewritten | The text became shorter; the roles were left in the details. |
| 12 | `settings-modules` | Modules | rewritten | Shortened without losing meaning. |
| 13 | `settings-about` | About the program | rewritten | Shortened for the tour card. |
| 14 | `printers-overview` | Your printers | rewritten | Shortened; status, progress and print time are kept. |
| 15 | `printers-sort` | Sort printers | rewritten | Simplified the purpose of sorting. |
| 16 | `printers-view` | List and grid view | rewritten | The name and the text were aligned with "list/grid". |
| 17 | `printers-add` | Add a printer | rewritten | Clarified adding the model and the connection parameters. |
| 18 | `printer-card-grid` | Compact printer card | rewritten | Separated the short text and the details about colors. |
| 19 | `printer-card-expanded` | Expanded printer card | rewritten | Clarified the buttons and the state of the bottom row during printing. |
| 20 | `printer-ams-print` | Print with AMS | rewritten | Shortened and aligned with the term "print file". |
| 21 | `projects-overview` | Projects | rewritten | A project is described as an order or a production batch. |
| 22 | `projects-create` | Create project | rewritten | Clarified creating an empty project and starting from files. |
| 23 | `projects-import-files` | Import project from files | rewritten | Shortened and tied to production preparation. |
| 24 | `projects-part-counters` | Counters in project | rewritten | The terms On plate / Needed / Printed are fixed explicitly. |
| 25 | `projects-label-objects` | Label Objects for counting | rewritten | Label Objects is explained through counting reliability. |
| 26 | `projects-counting-fallback` | If counting is unavailable | rewritten | Clarified that the program must not guess. |
| 27 | `projects-card` | Project card | rewritten | Removed extra length; the By part / By file modes are kept. |
| 28 | `projects-archive` | Archive | rewritten | Shortened the purpose of the archive. |
| 29 | `quick-tasks-overview` | Quick Tasks | rewritten | Quick Tasks is described as individual files without a project. |
| 30 | `quick-tasks-drop` | Drop or select a file | rewritten | Separated ready print files and models for the slicer. |
| 31 | `quick-tasks-load` | Load into Quick Tasks | rewritten | The term "print file" and clear file manager behaviour. |
| 32 | `quick-tasks-row` | Quick Task row | rewritten | The Russian labels for Needed/Printed were aligned with the "Needed"/"Printed" columns. |
| 33 | `quick-tasks-find-printer` | Find the printer | rewritten | Shortened to the main action. |
| 34 | `suggestions-alerts` | Suggestions and alerts | rewritten | Alerts are described as problems that need attention. |
| 35 | `finish` | You are all set | rewritten | The final step became shorter and less promotional. |
