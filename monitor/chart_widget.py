import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class ChartWidget:
    """
    Encapsulates a matplotlib Figure + Axis + Tk Canvas for one metric.
    Supports sliding window (keep only last N points) and lightweight redraw.
    """
    def __init__(self, parent, title, ylabel, max_points_var):
        self.parent = parent
        self.title = title
        self.ylabel = ylabel
        self.max_points_var = max_points_var

        self.fig = Figure(figsize=(6, 2.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(self.title)
        self.ax.set_xlabel("样本点")
        self.ax.set_ylabel(self.ylabel)
        self.ax.grid(True)
        self.line, = self.ax.plot([], [], marker='.', linestyle='-')

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def update(self, data_list):
        """ data_list: list of numeric values (already window-trimmed) """
        xs = list(range(len(data_list)))
        try:
            self.line.set_data(xs, data_list)
            self.ax.relim(); self.ax.autoscale_view()
            try:
                self.canvas.draw_idle()
            except Exception:
                self.canvas.draw()
        except Exception:
            pass

    def save_png(self, fname):
        self.fig.savefig(fname)
