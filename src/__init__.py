import logging
import sys
import threading
import subprocess
import gi
import json
import os
import time

from pathlib import Path

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio

Adw.init()

from . import info

BASE_DIR = Path(__file__).resolve().parent


def humanize(seconds):
    seconds = round(seconds)
    words = ["year", "day", "hour", "minute", "second"]

    if not seconds:
        return "now"
    else:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        y, d = divmod(d, 365)

        time = [y, d, h, m, s]

        duration = []

        for x, i in enumerate(time):
            if i == 1:
                duration.append(f"{i} {words[x]}")
            elif i > 1:
                duration.append(f"{i} {words[x]}s")

        if len(duration) == 1:
            return duration[0]
        elif len(duration) == 2:
            return f"{duration[0]} and {duration[1]}"
        else:
            return ", ".join(duration[:-1]) + " and " + duration[-1]


# metadata returns the file's resolution, framerate, and audio bitrate
def metadata(file) -> (float, float, float, float):
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            file,
        ]
        logging.debug("Running ffprobe: " + " ".join(cmd))
        x = subprocess.Popen(cmd, stdout=subprocess.PIPE).stdout.read()
        m = json.loads(x)
        streams = m["streams"]
        video = streams[0]
        audio = streams[1]
        r_fps = video["r_frame_rate"]
        if "/" in r_fps:
            r_fps = r_fps.split("/")
            r_fps = float(float(r_fps[0]) / float(r_fps[1]))
        r_fps = round(r_fps, 2)

        return video["width"], video["height"], r_fps, float(audio["sample_rate"]) / 1000
    except Exception as e:
        logging.error("Get metadata:", e)
        return 0, 0, 0, 0


def notify(text):
    application = Gtk.Application.get_default()
    notification = Gio.Notification.new(title="Aviator")
    notification.set_body(text)
    application.send_notification(None, notification)


def first_open():
    startup_file = os.path.join(Path.home(), ".var/app/net.natesales.Aviator/startup.dat")
    if os.path.exists(startup_file):
        return False
    else:
        with open(startup_file, "w") as f:
            f.write("\n")
        return True


class FileSelectDialog(Gtk.FileChooserDialog):
    home = Path.home()

    def __init__(self, parent, select_multiple, label, selection_text, open_only, callback=None):
        super().__init__(transient_for=parent, use_header_bar=True)
        self.select_multiple = select_multiple
        self.label = label
        self.callback = callback
        self.set_action(action=Gtk.FileChooserAction.OPEN if open_only else Gtk.FileChooserAction.SAVE)
        self.set_title(title="Select " + selection_text + " files" if self.select_multiple else "Select " + selection_text + " file")
        self.set_modal(modal=True)
        self.set_select_multiple(select_multiple=self.select_multiple)
        self.connect("response", self.dialog_response)
        self.set_current_folder(Gio.File.new_for_path(path=str(self.home)))

        self.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Select", Gtk.ResponseType.OK
        )
        btn_select = self.get_widget_for_response(response_id=Gtk.ResponseType.OK)
        btn_select.get_style_context().add_class(class_name="suggested-action")
        btn_cancel = self.get_widget_for_response(response_id=Gtk.ResponseType.CANCEL)
        btn_cancel.get_style_context().add_class(class_name="destructive-action")

        self.show()

    def dialog_response(self, widget, response):
        if response == Gtk.ResponseType.OK:
            if self.select_multiple:
                gliststore = self.get_files()
                for glocalfile in gliststore:
                    print(glocalfile.get_path())
            else:
                glocalfile = self.get_file()
                # print(glocalfile.get_path())
                self.label.set_label(glocalfile.get_path())
        if self.callback is not None:
            self.callback()
        widget.close()


class AboutDialog(Gtk.AboutDialog):
    def __init__(self, win):
        Gtk.AboutDialog.__init__(self)
        self.props.transient_for = win
        self.props.modal = True
        self.props.license_type = Gtk.License.AGPL_3_0
        self.props.program_name = "Aviator"
        self.props.logo_icon_name = "net.natesales.Aviator"
        self.props.version = "Aviator v" + info.version
        self.props.comments = "Your Video Copilot"
        self.props.copyright = "Copyright ?? 2022 Nate Sales and Gianni Rosato"
        self.props.website_label = "GitHub"
        self.props.website = "https://github.com/natesales/aviator"
        self.props.authors = ["Nate Sales <nate@natesales.net>", "Gianni Rosato <grosatowork@proton.me>"]


@Gtk.Template(filename=str(BASE_DIR.joinpath('startup.ui')))
class OnboardWindow(Adw.Window):
    __gtype_name__ = "OnboardWindow"

    image = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.image.set_from_file(
            filename=str(
                BASE_DIR.joinpath('net.natesales.Aviator-splash.png')
            )
        )

    @Gtk.Template.Callback()
    def go(self, button):
        app.win = MainWindow(application=app)
        app.win.present()
        self.destroy()


@Gtk.Template(filename=str(BASE_DIR.joinpath("window.ui")))
class MainWindow(Adw.Window):
    __gtype_name__ = "AviatorWindow"

    # Video page
    source_file_label = Gtk.Template.Child()
    resolution_width_entry = Gtk.Template.Child()
    resolution_height_entry = Gtk.Template.Child()
    framerate_entry = Gtk.Template.Child()
    crf_scale = Gtk.Template.Child()
    cpu_scale = Gtk.Template.Child()

    # Audio page
    bitrate_entry = Gtk.Template.Child()
    vbr_switch = Gtk.Template.Child()

    # Export page
    output_file_label = Gtk.Template.Child()
    container_mkv_button = Gtk.Template.Child()
    container_webm_button = Gtk.Template.Child()
    container = "mkv"
    encode_button = Gtk.Template.Child()
    encoding_spinner = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Default to MKV
        self.container_webm_button.set_has_frame(False)
        self.container_mkv_button.set_has_frame(True)
        self.container = "mkv"

        # Reset value to remove extra decimal
        self.cpu_scale.set_value(0)
        self.cpu_scale.set_value(6)
        self.crf_scale.set_value(0)
        self.crf_scale.set_value(32)

        # resolution, framerate, and audio bitrate
        self.metadata: (float, float, float, float) = ()

        # Absolute source path file
        self.source_file_absolute = ""

    def load_metadata(self):
        self.metadata = metadata(self.source_file_absolute)

    def set_defaults(self):
        self.bitrate_same_as_source()
        self.framerate_same_as_source()
        self.resolution_same_as_source()

    def handle_file_select(self):
        self.set_defaults()

        # Trim file path
        if "/" in self.source_file_label.get_text():
            self.source_file_absolute = self.source_file_label.get_text()
            self.source_file_label.set_text(os.path.basename(self.source_file_absolute))

    # Video

    @Gtk.Template.Callback()
    def open_source_file(self, button):
        FileSelectDialog(
            parent=self,
            select_multiple=False,
            label=self.source_file_label,
            selection_text="source",
            open_only=True,
            callback=self.handle_file_select
        )

    @Gtk.Template.Callback()
    def resolution_same_as_source(self, button=None):
        self.load_metadata()
        self.resolution_width_entry.set_text(str(self.metadata[0]))
        self.resolution_height_entry.set_text(str(self.metadata[1]))

    # Audio

    @Gtk.Template.Callback()
    def framerate_same_as_source(self, button=None):
        self.load_metadata()
        self.framerate_entry.set_text(str(round(float(self.metadata[2]))))

    @Gtk.Template.Callback()
    def bitrate_same_as_source(self, button=None):
        self.load_metadata()
        self.bitrate_entry.set_text(str(round(float(self.metadata[3]))))

    # Export

    @Gtk.Template.Callback()
    def open_output_file(self, button):
        FileSelectDialog(
            parent=self,
            select_multiple=False,
            label=self.output_file_label,
            selection_text="output",
            open_only=False,
        )

    @Gtk.Template.Callback()
    def container_mkv(self, button):
        self.container_webm_button.set_has_frame(False)
        self.container_mkv_button.set_has_frame(True)
        self.container = "mkv"

    @Gtk.Template.Callback()
    def container_webm(self, button):
        self.container_mkv_button.set_has_frame(False)
        self.container_webm_button.set_has_frame(True)
        self.container = "webm"

    @Gtk.Template.Callback()
    def start_export(self, button):
        self.encode_button.set_visible(False)
        self.encoding_spinner.set_visible(True)

        output = self.output_file_label.get_text()
        if self.container == "mkv" and not output.endswith(".mkv"):
            output += ".mkv"
        elif self.container == "webm" and not output.endswith(".webm"):
            output += ".webm"

        def run_in_thread():
            encode_start = time.time()
            cmd = [
                "ffmpeg",
                "-nostdin",
                "-i", self.source_file_absolute,
                "-r", self.framerate_entry.get_text(),
                "-vf", f"scale={self.resolution_width_entry.get_text()}:{self.resolution_height_entry.get_text()}",
                "-c:v", "libsvtav1",
                "-map", "0",
                "-crf", str(self.crf_scale.get_value()),
                "-preset", str(self.cpu_scale.get_value()),
                "-c:a", "libopus",
                "-b:a", self.bitrate_entry.get_text() + "K",
                "-vbr", "on" if self.vbr_switch.get_state() else "off",
                "-compression_level", "10",
                output,
            ]
            print(cmd)
            proc = subprocess.Popen(cmd)
            proc.wait()
            encode_end = time.time() - encode_start()

            self.encode_button.set_visible(True)
            self.encoding_spinner.set_visible(False)
            notify(f"({humanize(encode_end)}) Finished encoding {output}")

        thread = threading.Thread(target=run_in_thread)
        thread.start()


class App(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect("activate", self.on_activate)

        about_action = Gio.SimpleAction(name="about")
        about_action.connect("activate", self.about_dialog)
        self.add_action(about_action)

        quit_action = Gio.SimpleAction(name="quit")
        quit_action.connect("activate", self.quit)
        self.add_action(quit_action)

    def on_activate(self, app):
        if first_open():
            startup_window = OnboardWindow(application=self)
            startup_window.present()
        else:
            self.win = MainWindow(application=app)
            self.win.present()

    def about_dialog(self, action, user_data):
        dialog = AboutDialog(self.win)
        dialog.present()

    def quit(self, action=None, user_data=None):
        exit()


app = App(application_id="net.natesales.Aviator")
app.run(sys.argv)
