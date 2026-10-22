"""Windows 11 Live Captions -> separate AI practice answer window.
Requires Python 3.10+, openai, mss, pillow, pytesseract and Tesseract OCR.
"""
import difflib
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
import pytesseract

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if not os.path.isfile(TESSERACT_PATH):
    raise FileNotFoundError(
        f"Tesseract OCR not found at: {TESSERACT_PATH}"
    )

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

print("Tesseract version:", pytesseract.get_tesseract_version())

CONFIG_FILE = Path.home() / '.live_caption_assistant_config.json'
QUESTION_START = re.compile(r'^(what|why|how|when|where|who|which|can|could|would|will|do|does|did|is|are|have|has|tell me|describe|explain|walk me through|give me an example|please explain)\b', re.I)


def find_question(s):
    s = ' '.join(s.split()).strip()
    if not s or len(s) < 12:
        return None
    # Detect a question after multiple lines merged by OCR.
    parts = re.split(r'(?<=[?.!])\s+', s)
    for p in reversed(parts):
        p = p.strip()
        if len(p) >= 15 and (p.endswith('?') or QUESTION_START.search(p)):
            return p[-650:]
    return None


class SentenceRecorder:
    """Recover newly appended words from overlapping OCR frames and write complete sentences."""
    def __init__(self, path):
        self.path = Path(path)
        self.pending = ''
        self.previous = ''
        self.recent = []

    @staticmethod
    def normalize(text):
        return ' '.join(text.replace('\n', ' ').split()).strip()

    @staticmethod
    def tokens(text):
        return re.findall(r"\S+", text)

    @staticmethod
    def comparable(token):
        return re.sub(r'[^\w]+', '', token, flags=re.UNICODE).casefold()

    def new_segment(self, frame):
        """Find append-only changes or word overlap when captions scroll."""
        current = self.normalize(frame)
        if not current or current == self.previous:
            return ''
        old_words, new_words = self.tokens(self.previous), self.tokens(current)
        old = [self.comparable(w) for w in old_words]
        new = [self.comparable(w) for w in new_words]
        if not self.previous:
            fresh = new_words
        elif current.casefold().startswith(self.previous.casefold()):
            fresh = self.tokens(current[len(self.previous):])
            if not fresh and current != self.previous and current[-1] in '.!?':
                self.pending = self.pending.rstrip('.!?') + current[-1]
        else:
            match = 0
            for size in range(min(len(old), len(new)), 0, -1):
                if old[-size:] == new[:size]:
                    match = size
                    break
            if match:
                fresh = new_words[match:]
                # The OCR may add punctuation to the last word after a pause.
                if not fresh and old_words and new_words and old_words[-1] != new_words[-1]:
                    self.pending = re.sub(r'[^\w]*$', '', self.pending) + re.search(r'[^\w]*$', new_words[-1]).group()
            else:
                # If the entire frame is a cropped part of earlier text, don't duplicate it.
                comparable_current = [self.comparable(t) for t in new_words]
                if comparable_current and len(comparable_current) >= 3 and any(
                    old[i:i+len(new)] == comparable_current
                    for i in range(max(0, len(old)-len(new)+1))
                ):
                    fresh = []
                elif old and new and old[:min(len(old), len(new))] == new[:min(len(old), len(new))]:
                    fresh = new_words[len(old):]
                else:
                    # Captions may jump too far between samples, leading to gaps.
                    fresh = new_words
        self.previous = current
        return ' '.join(fresh)

    def ingest(self, frame):
        delta = self.new_segment(frame)
        if delta:
            self.pending = (self.pending + ' ' + delta).strip()
            self.pending = re.sub(r'\s+([.!?,;:])', r'\1', self.pending)
        written = []
        # Only a period, question mark, or exclamation mark is considered a clear
        # sentence ending. Keep trailing text pending until it is completed.
        while True:
            found = re.search(r'(?<!\d)[.!?](?=\s|$)', self.pending)
            if not found:
                break
            sentence = self.pending[:found.end()].strip()
            self.pending = self.pending[found.end():].strip()
            signature = re.sub(r'\W+', '', sentence).casefold()
            if len(signature) < 3 or signature in self.recent:
                continue
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as file:
                file.write(sentence + '\n')
            self.recent.append(signature)
            self.recent = self.recent[-100:]
            written.append(sentence)
        return written


class RegionPicker(tk.Toplevel):
    def __init__(self, master, on_region):
        super().__init__(master)
        self.on_region = on_region
        self.start = None
        self.rect = None
        # On Windows, Tk cannot combine override-redirect with fullscreen.
        # Fullscreen alone provides the overlay without window decorations.
        self.attributes('-fullscreen', True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.34)
        self.configure(bg='black')
        self.canvas = tk.Canvas(self, highlightthickness=0, cursor='crosshair', bg='black')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_text(40, 45, anchor='w', text='Drag around the LIVE CAPTIONS TEXT area  •  Esc to cancel',
                                font=('Segoe UI', 19, 'bold'), fill='white')
        self.canvas.bind('<ButtonPress-1>', self.down)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.up)
        self.bind('<Escape>', lambda e: (self.destroy(), self.master.deiconify()))
        self.focus_force()

    def down(self, e):
        self.start = (e.x_root, e.y_root)

    def drag(self, e):
        if not self.start:
            return
        x1, y1 = self.start
        x2, y2 = e.x_root, e.y_root
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline='#00ffcc', width=4)

    def up(self, e):
        if not self.start:
            return
        x1, y1 = self.start
        left, top = min(x1, e.x_root), min(y1, e.y_root)
        width, height = abs(e.x_root-x1), abs(e.y_root-y1)
        self.destroy()
        if width > 90 and height > 25:
            self.on_region({'left': left, 'top': top, 'width': width, 'height': height})


class App:
    def __init__(self, root):
        self.root = root
        root.title('Live Captions → AI Practice Answers')
        root.geometry('820x690')
        root.minsize(650, 540)
        self.events = queue.Queue()
        self.stop_signal = threading.Event()
        self.running = False
        self.inflight = False
        self.last_image_text = ''
        self.last_sent = ''
        self.last_question_at = 0.0
        self.text_history = []
        self.region = None
        self.transcript_path = Path.home() / 'Documents' / 'LiveCaptions' / 'captions.txt'
        self.recorder = SentenceRecorder(self.transcript_path)
        self.model = tk.StringVar(value=os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini'))
        self.auto = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Ready. Start Windows Live Captions (Win + Ctrl + L).')
        self.region_label = tk.StringVar(value='No area selected')
        self.build_ui()
        self.load_config()
        root.after(150, self.process_events)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Live Captions → AI Practice Answers', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Select the on-screen caption area. The app reads it locally using OCR and answers detected questions.', wraplength=760).pack(anchor='w', pady=(4, 13))
        row1 = ttk.Frame(outer)
        row1.pack(fill='x')
        ttk.Button(row1, text='1  Select caption area', command=self.pick_region).pack(side='left', padx=(0, 10))
        ttk.Label(row1, textvariable=self.region_label).pack(side='left')
        row2 = ttk.Frame(outer)
        row2.pack(fill='x', pady=10)
        self.start_button = ttk.Button(row2, text='2  Start reading', command=self.toggle)
        self.start_button.pack(side='left', padx=(0, 10))
        ttk.Button(row2, text='Generate answer now', command=self.generate_now).pack(side='left', padx=(0, 10))
        ttk.Checkbutton(row2, text='Auto-answer detected questions', variable=self.auto).pack(side='left')
        settings = ttk.Frame(outer)
        settings.pack(fill='x', pady=(0, 10))
        ttk.Label(settings, text='Model:').pack(side='left')
        ttk.Entry(settings, textvariable=self.model, width=21).pack(side='left', padx=(7, 10))
        ttk.Label(settings, text='API key: OPENAI_API_KEY environment variable', foreground='#555555').pack(side='left')
        ttk.Label(outer, text='Sentence transcript file: ' + str(self.transcript_path), wraplength=760).pack(anchor='w', pady=(0, 7))
        ttk.Label(outer, text='Latest recognized caption:').pack(anchor='w')
        self.caption_box = scrolledtext.ScrolledText(outer, height=6, wrap='word', font=('Segoe UI', 11))
        self.caption_box.pack(fill='both', pady=(4, 12))
        ttk.Label(outer, text='Suggested practice answer:', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.answer_box = scrolledtext.ScrolledText(outer, height=13, wrap='word', font=('Segoe UI', 12))
        self.answer_box.pack(fill='both', expand=True, pady=(4, 10))
        self.answer_box.insert('1.0', 'Answers will appear here. You can also paste a question into the caption box and select “Generate answer now” to test the API.')
        ttk.Label(outer, textvariable=self.status, wraplength=760).pack(anchor='w')

    def load_config(self):
        try:
            d = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            r = d.get('region')
            if r and all(k in r for k in ('left', 'top', 'width', 'height')):
                self.set_region(r, persist=False)
            if d.get('model'):
                self.model.set(d['model'])
        except (OSError, ValueError, TypeError):
            pass

    def set_region(self, region, persist=True):
        self.region = region
        self.region_label.set(f"Area: {region['width']} × {region['height']} at ({region['left']}, {region['top']})")
        if persist:
            try:
                CONFIG_FILE.write_text(json.dumps({'region': region, 'model': self.model.get()}), encoding='utf-8')
            except OSError:
                pass

    def pick_region(self):
        if self.running:
            messagebox.showinfo('Stop first', 'Stop reading before selecting a different area.')
            return
        self.root.withdraw()
        # Important: ensure underlying caption area remains visible.
        self.root.after(350, lambda: RegionPicker(self.root, self.finish_selection))

    def finish_selection(self, region):
        self.root.deiconify()
        self.set_region(region)
        self.status.set('Caption area selected. Press Start reading.')

    def toggle(self):
        if self.running:
            self.stop_signal.set()
            self.running = False
            self.start_button.configure(text='2  Start reading')
            self.status.set('Stopped.')
            return
        if not self.region:
            messagebox.showwarning('Select caption area', 'Select the on-screen caption area first.')
            return
        try:
            import mss, pytesseract  # noqa: F401
            import PIL  # noqa: F401
        except ImportError:
            messagebox.showerror('Dependencies missing', 'Run: py -m pip install openai mss pillow pytesseract')
            return
        self.stop_signal.clear()
        self.running = True
        self.start_button.configure(text='Stop reading')
        self.status.set('Reading captions every 1.5 seconds ...')
        threading.Thread(target=self.capture_loop, daemon=True).start()

    def capture_loop(self):
        try:
            import mss
            from PIL import Image, ImageEnhance, ImageOps
            # Capture only selected pixels. No screenshot files are saved.
            with mss.MSS() as sct:
                while not self.stop_signal.is_set():
                    shot = sct.grab(self.region)
                    im = Image.frombytes('RGB', shot.size, shot.rgb)
                    im = ImageOps.grayscale(im)
                    im = ImageEnhance.Contrast(im).enhance(2)
                    recognized = ' '.join(pytesseract.image_to_string(im, config='--psm 6').split()).strip()
                    if recognized and self.is_new_caption(recognized):
                        self.events.put(('caption', recognized))
                    if self.stop_signal.wait(1.5):
                        return
        except Exception as ex:
            self.events.put(('error', f'OCR failed: {ex}. Verify Tesseract is installed and available in PATH.'))

    def is_new_caption(self, text):
        previous = self.last_image_text
        if text == previous or difflib.SequenceMatcher(None, text.lower(), previous.lower()).ratio() > .96:
            return False
        self.last_image_text = text
        return True

    def received_caption(self, text):
        try:
            saved = self.recorder.ingest(text)
            if saved:
                self.status.set(f'Saved {len(saved)} completed sentence(s) to captions.txt')
        except OSError as ex:
            self.status.set(f'Could not save transcript: {ex}')
        self.caption_box.delete('1.0', 'end')
        self.caption_box.insert('1.0', text)
        self.text_history.append(text)
        self.text_history = self.text_history[-6:]
        if not self.status.get().startswith(('Saved ', 'Could not save')):
            self.status.set('Listening for an interview question...')
        question = find_question(text)
        if not question or not self.auto.get():
            return
        signature = re.sub(r'\W+', ' ', question.lower()).strip()
        similarity = difflib.SequenceMatcher(None, signature, self.last_sent).ratio()
        # Rate limit/cooldown avoids repeated API calls as captions repaint and change.
        if similarity > .70 or self.inflight or time.time() - self.last_question_at < 12:
            return
        self.request_answer(question, signature)

    def generate_now(self):
        question = self.caption_box.get('1.0', 'end').strip()
        if not question:
            messagebox.showinfo('No text', 'Type a practice question or start caption capture first.')
            return
        if self.inflight:
            self.status.set('An answer is already being generated.')
            return
        self.request_answer(question, re.sub(r'\W+', ' ', question.lower()).strip())

    def request_answer(self, question, signature):
        if not os.environ.get('OPENAI_API_KEY'):
            self.status.set('OPENAI_API_KEY not found. Set it in PowerShell before launching this app.')
            return
        self.inflight = True
        self.last_sent = signature
        self.last_question_at = time.time()
        self.status.set('Generating an answer...')
        self.answer_box.delete('1.0', 'end')
        self.answer_box.insert('1.0', f'Question: {question}\n\nGenerating practice answer...')
        threading.Thread(target=self.answer_worker, args=(question, self.model.get().strip()), daemon=True).start()

    def answer_worker(self, question, model):
        try:
            from openai import OpenAI
            client = OpenAI(timeout=30.0, max_retries=1)
            response = client.responses.create(
                model=model or 'gpt-4.1-mini',
                store=False,
                instructions=(
                    'You coach candidates practicing for job interviews. '
                    'Offer a concise example answer in plain English (3 to 6 sentences). '
                    'For technical questions, explain accurately and simply. '
                    'For personal-experience questions, do not invent facts about the user: '
                    'label it as a sample and encourage adapting to their actual experience.'
                ),
                input=question[:2500],
            )
            self.events.put(('answer', (question, response.output_text or 'No text returned.')))
        except Exception as ex:
            self.events.put(('answer_error', str(ex)))

    def process_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == 'caption':
                    self.received_caption(value)
                elif event == 'answer':
                    self.inflight = False
                    question, answer = value
                    self.answer_box.delete('1.0', 'end')
                    self.answer_box.insert('1.0', f'QUESTION\n{question}\n\nSUGGESTED ANSWER\n{answer}')
                    self.status.set('Answer ready. Watching for the next question.' if self.running else 'Answer ready.')
                elif event == 'answer_error':
                    self.inflight = False
                    self.status.set('API request failed. Check the error below.')
                    self.answer_box.delete('1.0', 'end')
                    self.answer_box.insert('1.0', f'API error: {value}')
                elif event == 'error':
                    self.running = False
                    self.stop_signal.set()
                    self.start_button.configure(text='2  Start reading')
                    self.status.set(value)
        except queue.Empty:
            pass
        self.root.after(150, self.process_events)

    def close(self):
        self.stop_signal.set()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
