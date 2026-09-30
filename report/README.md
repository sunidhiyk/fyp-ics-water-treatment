# Final Report and Presentation

| File | What it is |
|---|---|
| `FYP_Final_Report.docx` | Editable final report (37 pages) |
| `FYP_Final_Report.pdf` | The same report as a PDF, with the table of contents and lists filled in |
| `FYP_Final_Presentation.pptx` | 15-slide presentation with speaker notes |
| `figures/` | Figures used in the report and slides |
| `make_figures.py` | Rebuilds `figures/architecture.png` and `figures/dataset_timeline.png` |
| `build/` | Scripts that generate the .docx and .pptx |

**Before submitting,** replace the placeholders in square brackets on the title
page and the first slide: university, department, member names and roll
numbers, supervisor, and month/year.

**Table of contents in the .docx.** When you open the .docx, Word asks whether to
update the fields in the document. Choose **Yes** to fill in the table of
contents and the lists of figures and tables. If they are ever empty, right-click
them and choose **Update Field → Update entire table**.

## Rebuilding

The documents are generated from the project's results, so they can be rebuilt
after a result changes:

```bash
python -m report.make_figures          # figures that are not produced by eval/
cd report/build
npm install
UPDATE_FIELDS=1 node build_report.js   # -> report/FYP_Final_Report.docx
node build_slides.js                   # -> report/FYP_Final_Presentation.pptx
```

Rebuilding overwrites any edits made directly in Word or PowerPoint. The PDF was
exported from Word.
