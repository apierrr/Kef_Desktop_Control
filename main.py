import asyncio
import aiokef # pyright: ignore[reportMissingImports]
import nest_asyncio # pyright: ignore[reportMissingImports]
import sys
import customtkinter as ctk # pyright: ignore[reportMissingImports]
import os

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

nest_asyncio.apply()

ip_lsx = "192.168.1.10"
lsx = aiokef.AsyncKefSpeaker(ip_lsx)



async def kef_aux():
    await lsx.set_source("Aux")

async def kef_bluetooth():
    await lsx.set_source("Bluetooth")

async def kef_opt():
    await lsx.set_source("Optical")

async def kef_wifi():
    await lsx.set_source("Wifi")

async def turn_off():
    await lsx.turn_off()

def run_async_task(coro):
    loop = asyncio.get_event_loop()
    loop.create_task(coro)

async def get_volume():
    volume = await lsx.get_volume()
    return int(volume * 100)  # Convert 0.0-1.0 to 0-100

async def set_volume(volume: int):
    volume = max(0, min(100, volume))
    await lsx.set_volume(volume / 100)

class KefGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("KEF Controller")
        self.geometry("420x420")
        self.resizable(False, False)
        self.iconbitmap(resource_path("kef.ico"))

        # États pour gestion du drag et volume en attente
        self.is_dragging = False
        self.pending_volume = None
        self.drag_timeout_id = None

        # Boutons sources
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=30)
        btn_opts = {"master": btn_frame, "width": 160, "height": 48, "corner_radius": 16, "font": ("SF Pro Display", 18, "bold")}
        ctk.CTkButton(**btn_opts, text="Aux", command=lambda: run_async_task(kef_aux())).grid(row=0, column=0, padx=16, pady=10)
        ctk.CTkButton(**btn_opts, text="Bluetooth", command=lambda: run_async_task(kef_bluetooth())).grid(row=0, column=1, padx=16, pady=10)
        ctk.CTkButton(**btn_opts, text="Optical", command=lambda: run_async_task(kef_opt())).grid(row=1, column=0, padx=16, pady=10)
        ctk.CTkButton(**btn_opts, text="Wifi", command=lambda: run_async_task(kef_wifi())).grid(row=1, column=1, padx=16, pady=10)
        ctk.CTkButton(self, text="Turn Off", command=lambda: run_async_task(turn_off()), width=340, height=40, corner_radius=16, fg_color="#e74c3c", hover_color="#c0392b", font=("SF Pro Display", 16, "bold")).pack(pady=(0, 30))

        # Volume
        self.volume_label = ctk.CTkLabel(self, text="Volume: ...", font=("SF Pro Display", 32, "bold"))
        self.volume_label.pack(pady=(0, 10))

        self.volume_scale = ctk.CTkSlider(self, from_=0, to=100, width=340, height=24, command=self.on_volume_drag, number_of_steps=100)
        self.volume_scale.pack(pady=(0, 10))
        self.volume_scale.bind('<ButtonRelease-1>', self.on_volume_release)
        self.volume_scale.bind('<ButtonPress-1>', self.on_volume_press)

        self.update_volume_display()


    def on_volume_press(self, event=None):
        self.is_dragging = True
        # Si un timeout précédent existe, l'annuler
        if self.drag_timeout_id:
            self.after_cancel(self.drag_timeout_id)
            self.drag_timeout_id = None

    def on_volume_drag(self, value):
        # Affiche le volume choisi en temps réel et bloque update auto
        value = int(float(self.volume_scale.get()))
        self.pending_volume = value
        self.volume_label.configure(text=f"Volume: {value}")

    def on_volume_release(self, event=None):
        value = int(float(self.volume_scale.get()))
        self.pending_volume = value
        self.is_dragging = False
        run_async_task(self._set_and_confirm_volume(value))

    async def _set_and_confirm_volume(self, value):
        try:
            await set_volume(value)
        except Exception as e:
            self.volume_label.configure(text=f"Erreur: {e}")
        # Après confirmation, on laisse la valeur affichée jusqu'à la prochaine update réelle
        self.pending_volume = None
        # On attend un court délai avant de réactiver update auto (pour éviter snap-back)
        def clear_pending():
            self.pending_volume = None
            self.update_volume_display()
        self.drag_timeout_id = self.after(600, clear_pending)

    def update_volume_display(self):
        # Si on est en drag ou en attente de confirmation, ne pas écraser l'affichage
        if self.is_dragging or self.pending_volume is not None:
            self.after(500, self.update_volume_display)
            return
        async def update():
            try:
                vol = await get_volume()
                self.volume_label.configure(text=f"Volume: {vol}")
                self.volume_scale.set(vol)
            except Exception as e:
                self.volume_label.configure(text=f"Erreur: {e}")
            self.after(2000, self.update_volume_display)
        run_async_task(update())



def resource_path(relative_path):
    """Trouve le chemin du fichier dans le bundle PyInstaller ou en dev."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    gui = KefGUI()
    def poll_loop():
        try:
            loop.call_soon(loop.stop)
            loop.run_forever()
        except Exception:
            pass
        gui.after(50, poll_loop)
    gui.after(50, poll_loop)
    gui.mainloop()

if __name__ == "__main__":
    main()