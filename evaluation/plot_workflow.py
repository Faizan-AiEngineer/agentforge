import csv
from collections import defaultdict
from statistics import mean

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors

from backend.app.runtime import PROJECT


def main():
    samples = defaultdict(list)
    with (PROJECT / "evaluation/results/workflow_performance.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            if row["status"] == "SUCCEEDED":
                samples[int(row["nodes"])].append(float(row["execution_ms"]) / 1000)
    points = sorted((size, mean(durations)) for size, durations in samples.items())
    ink, gray, accent = map(colors.HexColor, ("#16253d", "#5b6a82", "#138b79"))
    drawing = Drawing(620, 345)
    drawing.add(String(54, 312, "Local workflow execution time", fillColor=ink,
                       fontName="Helvetica-Bold", fontSize=21))
    drawing.add(String(54, 290, "Mean successful duration in seconds", fillColor=gray, fontSize=11))
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 62, 56, 495, 201
    plot.data = [points]
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, 105
    plot.xValueAxis.valueSteps = [0, 25, 50, 75, 100]
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = 0, 8
    plot.yValueAxis.valueSteps = [0, 2, 4, 6, 8]
    plot.lines[0].strokeColor = accent
    plot.lines[0].strokeWidth = 2.5
    drawing.add(plot)
    drawing.add(String(290, 24, "Nodes per workflow", fillColor=gray, fontSize=11))
    output = PROJECT / "evaluation/reports/figures"
    output.mkdir(parents=True, exist_ok=True)
    (output / "workflow-duration.pdf").write_bytes(drawing.asString("pdf"))


if __name__ == "__main__":
    main()
