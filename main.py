import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests
import datetime
import os
import threading
import queue

def generate_forecast_hours(model):
    """Generates a list of forecast hours based on the model's typical run schedule."""
    if model in ['gfs', 'ecmwf_full']:
        return list(range(0, 241, 3)) + list(range(246, 385, 6))
    elif model == 'nam':
        return list(range(0, 85, 1))
    elif model == 'hrrr':
        return list(range(0, 49, 1))
    else:
        return list(range(0, 241, 6))

def generate_run_times():
    """Generates a dictionary of the last 8 model run times for the UI."""
    run_times = {}
    now_utc = datetime.datetime.utcnow()
    for i in range(8):
        run_time_to_check = now_utc - datetime.timedelta(hours=i * 6)
        run_hour = (run_time_to_check.hour // 6) * 6
        dt_obj = run_time_to_check.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        display_text = dt_obj.strftime('%Y-%m-%d %HZ')
        if i == 0: display_text += " (Latest)"
        run_time_str = dt_obj.strftime('%Y%m%d%H')
        run_times[display_text] = run_time_str
    return run_times

def threaded_fetch_image_sequence(q, base_url, model, run_time, parameter, region, save_dir="weather_images"):
    """
    This function runs in a separate thread to download images without freezing the GUI.
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    forecast_hours = generate_forecast_hours(model)
    downloaded_paths = []
    total_images = len(forecast_hours)
    consecutive_failures = 0

    for i, hour in enumerate(forecast_hours):
        q.put({"type": "progress", "value": (i + 1) / total_images * 100})
        forecast_hour_str = f"{hour:03d}"
        url = f"{base_url}/maps/models/{model}/{run_time}/{forecast_hour_str}/{parameter}.{region}.png"
        file_path = os.path.join(save_dir, f"{model}_{run_time}_{forecast_hour_str}_{parameter}_{region}.png")
        
        try:
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                consecutive_failures = 0
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                downloaded_paths.append(file_path)
            else:
                print(f"Skipping F{hour} for run {run_time}: Not found (status {response.status_code})")
                consecutive_failures += 1
        except requests.exceptions.RequestException as e:
            print(f"Network error on F{hour}: {e}")
            consecutive_failures += 1
        
        if consecutive_failures >= 3:
            print("Stopping download: 3 consecutive frames were not found.")
            q.put({"type": "progress", "value": 100})
            break

    q.put({"type": "result", "run_time": run_time, "paths": downloaded_paths})
    return

class WeatherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Weather Model Viewer")
        self.geometry("1100x850")

        # --- DATA DICTIONARIES (UPDATED BASED ON YOUR FEEDBACK) ---
        self.models = {
            "GFS": "gfs",
            "NAM": "nam",
            "HRRR": "hrrr",
            "ECMWF": "ecmwf_full"
        }
        
        self.base_urls = {
            "gfs": "https://m1o.pivotalweather.com",
            "nam": "https://m1o.pivotalweather.com",
            "hrrr": "https://m2o.pivotalweather.com",
            "ecmwf_full": "https://m1o.pivotalweather.com"
        }
        
        self.parameters = {
            # -- Severe Weather --
            "Composite Reflectivity": "refcmp",
            "Supercell Composite": "scp",
            "Significant Tornado": "stp",
            "Surface-Based CAPE": "sbcape",
            "Most Unstable CAPE": "mucape",
            "Updraft Helicity (0-3km)": "uh03_max",
            "Storm Relative Helicity (0-3km)": "srh03",
            "Surface-500mb Bulk Shear": "bs0500",
            # -- Winter Weather --
            "Precipitation Type": "prateptype_cat-imp",
            "24hr Kuchera Snow Accum": "snku_024h-imp",
            "Snow Depth": "snod-imp",
            # -- General / Synoptic --
            "Surface Temp": "sfct-imp",
            "2m Dewpoint": "sfctd-imp",
            "Surface Relative Humidity": "sfcrh",
            "Mean Sea Level Pressure": "pmsl_mslp",
            "10m Wind": "10mwind",
            "24hr Total Precipitation": "qpf_024h-imp",
            # -- Upper Air --
            "500mb Height & Vorticity": "500hv",
        }
        
        self.regions = {
            "Continental US": "conus", "Northeast US": "us_ne", "Southeast US": "us_se",
            "Midwest US": "us_mw", "South Central US": "us_sc", "North Central US": "us_nc",
            "Southwest US": "us_sw", "West Coast US": "us_wn", "Pacific Northwest": "us_pnw",
            "North America": "n_america", "Canada": "canada", "Alaska": "alaska", "Europe": "europe",
        }
        
        # --- App State & UI Variables ---
        self.run_times = generate_run_times()
        self.image_paths = []
        self.current_frame_index = 0
        self.model_run_time = None
        self.is_playing = False
        self.animation_job = None
        self.fetch_queue = queue.Queue()
        self.model_var = tk.StringVar(value="GFS")
        self.region_var = tk.StringVar(value="Continental US")
        self.param_var = tk.StringVar(value=list(self.parameters.keys())[0])
        self.run_time_var = tk.StringVar(value=list(self.run_times.keys())[0])
        
        # --- UI LAYOUT (No changes needed here) ---
        self.setup_ui()
        
    def setup_ui(self):
        control_frame = ttk.Frame(self, padding="10")
        control_frame.pack(side="top", fill="x")
        self.info_frame = ttk.Frame(self, padding=(10,0))
        self.info_frame.pack(side="top", fill="x")
        self.animation_frame = ttk.Frame(self, padding=(10, 5))
        self.image_frame = ttk.Frame(self, padding="10")
        self.image_frame.pack(side="top", fill="both", expand=True)
        ttk.Label(control_frame, text="Model:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        ttk.OptionMenu(control_frame, self.model_var, self.model_var.get(), *self.models.keys()).grid(row=1, column=0, sticky="ew")
        ttk.Label(control_frame, text="Model Run:").grid(row=0, column=1, padx=5, pady=2, sticky="w")
        ttk.OptionMenu(control_frame, self.run_time_var, self.run_time_var.get(), *self.run_times.keys()).grid(row=1, column=1, sticky="ew")
        ttk.Label(control_frame, text="Region:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ttk.OptionMenu(control_frame, self.region_var, self.region_var.get(), *self.regions.keys()).grid(row=1, column=2, sticky="ew")
        ttk.Label(control_frame, text="Parameter:").grid(row=0, column=3, padx=5, pady=2, sticky="w")
        ttk.OptionMenu(control_frame, self.param_var, self.param_var.get(), *self.parameters.keys()).grid(row=1, column=3, sticky="ew")
        self.fetch_button = ttk.Button(control_frame, text="Fetch Sequence", command=self.start_fetch_thread)
        self.fetch_button.grid(row=0, column=4, rowspan=2, padx=20, pady=5, sticky="ns")
        self.progress_bar = ttk.Progressbar(control_frame, orient='horizontal', mode='determinate')
        self.progress_bar.grid(row=2, column=0, columnspan=5, sticky='ew', pady=(10,0))
        for i in range(4): control_frame.columnconfigure(i, weight=1)
        self.run_time_label = ttk.Label(self.info_frame, text="Model Run: --")
        self.run_time_label.pack(side="left", padx=10)
        self.forecast_hour_label = ttk.Label(self.info_frame, text="Forecast Hour: --")
        self.forecast_hour_label.pack(side="left", padx=10)
        self.valid_time_label = ttk.Label(self.info_frame, text="Valid Time: --")
        self.valid_time_label.pack(side="left", padx=10)
        self.play_button = ttk.Button(self.animation_frame, text="▶ Play", command=self.toggle_play_pause, state="disabled")
        self.play_button.pack(side="left")
        self.prev_button = ttk.Button(self.animation_frame, text="< Prev", command=self.prev_frame, state="disabled")
        self.prev_button.pack(side="left")
        self.frame_slider = ttk.Scale(self.animation_frame, from_=0, to=100, orient="horizontal", command=self.on_slider_move, state="disabled")
        self.frame_slider.pack(side="left", fill="x", expand=True, padx=10)
        self.next_button = ttk.Button(self.animation_frame, text="Next >", command=self.next_frame, state="disabled")
        self.next_button.pack(side="left")
        self.image_label = ttk.Label(self.image_frame, text="Select parameters and click 'Fetch' to begin.", anchor="center")
        self.image_label.pack(fill="both", expand=True)
        self.tk_image = None
        
    def start_fetch_thread(self):
        self.fetch_button.config(state="disabled")
        self.progress_bar['value'] = 0
        self.set_animation_controls_state("disabled")
        self.image_label.config(image='', text="Please wait, fetching data...\nThis may take a moment.")
        
        model_name = self.model_var.get()
        model_code = self.models[model_name]
        base_url = self.base_urls[model_code]
        run_time_key = self.run_time_var.get()
        run_time_code = self.run_times[run_time_key]

        self.thread = threading.Thread(
            target=threaded_fetch_image_sequence,
            args=(self.fetch_queue, base_url, model_code, run_time_code,
                  self.parameters[self.param_var.get()],
                  self.regions[self.region_var.get()])
        )
        self.thread.daemon = True
        self.thread.start()
        self.after(100, self.process_queue)

    def process_queue(self):
        try:
            message = self.fetch_queue.get_nowait()
            if message["type"] == "progress":
                self.progress_bar['value'] = message["value"]
            elif message["type"] == "result":
                self.handle_fetch_results(message["run_time"], message["paths"])
                return
        except queue.Empty:
            pass
        self.after(100, self.process_queue)

    def handle_fetch_results(self, run_time, paths):
        self.progress_bar['value'] = 0
        if paths:
            self.model_run_time = run_time
            self.image_paths = paths
            self.current_frame_index = -1
            self.frame_slider.config(to=len(paths) - 1 if paths else 0)
            self.display_frame(0)
            self.set_animation_controls_state("normal")
            self.animation_frame.pack(side="top", fill="x", before=self.image_frame)
        else:
            run_time_key = self.run_time_var.get()
            messagebox.showwarning("Download Failed", f"Could not download any images for the {run_time_key} run. The selected parameter may not be available for this model.")
            self.image_label.config(text="Select parameters and click 'Fetch' to begin.")
        
        self.fetch_button.config(state="normal")
        
    def display_frame(self, index):
        if not self.image_paths or not (0 <= index < len(self.image_paths)): return
        self.current_frame_index = index
        if int(self.frame_slider.get()) != index: self.frame_slider.set(index)
        filepath = self.image_paths[index]
        try:
            img = Image.open(filepath)
            self.tk_image = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.tk_image)
            filename = os.path.basename(filepath)
            parts = filename.split('_')
            hour_str = parts[2]
            run_dt_obj = datetime.datetime.strptime(self.model_run_time, "%Y%m%d%H")
            valid_dt_obj = run_dt_obj + datetime.timedelta(hours=int(hour_str))
            self.run_time_label.config(text=f"Model Run: {run_dt_obj.strftime('%Y-%m-%d %H:%M')}Z")
            self.forecast_hour_label.config(text=f"Forecast Hour: F{hour_str}")
            self.valid_time_label.config(text=f"Valid Time: {valid_dt_obj.strftime('%Y-%m-%d %H:%M')}Z")
        except Exception as e:
            self.image_label.config(image='', text=f"Error displaying image:\n{filepath}\n{e}")

    def on_slider_move(self, value):
        self.display_frame(int(float(value)))

    def next_frame(self):
        if not self.image_paths: return
        new_index = (self.current_frame_index + 1) % len(self.image_paths)
        self.display_frame(new_index)

    def prev_frame(self):
        if not self.image_paths: return
        new_index = (self.current_frame_index - 1 + len(self.image_paths)) % len(self.image_paths)
        self.display_frame(new_index)
        
    def toggle_play_pause(self):
        if self.is_playing:
            self.is_playing = False
            self.play_button.config(text="▶ Play")
            if self.animation_job: self.after_cancel(self.animation_job)
        else:
            self.is_playing = True
            self.play_button.config(text="❚❚ Pause")
            self.animate()

    def animate(self):
        if self.is_playing:
            self.next_frame()
            self.animation_job = self.after(200, self.animate)

    def set_animation_controls_state(self, state):
        for widget in [self.play_button, self.prev_button, self.frame_slider, self.next_button]:
            widget.config(state=state)

if __name__ == '__main__':
    app = WeatherApp()
    app.mainloop()