import os
import sqlite3
import shutil
import pandas as pd
from datetime import datetime
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import Image
from kivy.core.window import Window
from kivy.uix.spinner import Spinner
from kivy.graphics import Color, Rectangle

# PDF export
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

DB_NAME = "loans.db"
DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

# Set window size
Window.size = (300, 400)


def parse_loan_date(value):
    """Read both form dates and legacy database timestamp dates."""
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), date_format).date()
        except (TypeError, ValueError):
            pass
    raise ValueError("Date must be in DD/MM/YYYY format.")


def calculate_completed_months(loan_date, current_date):
    """Return the number of fully completed calendar months."""
    months = (current_date.year - loan_date.year) * 12 + current_date.month - loan_date.month
    if current_date.day < loan_date.day:
        months -= 1
    return max(0, months)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        mobile TEXT NOT NULL,
        address TEXT NOT NULL,
        reference TEXT NOT NULL,
        additional_mobile TEXT NOT NULL,
        comments TEXT NOT NULL,
        principal_amount REAL NOT NULL,
        interest REAL NOT NULL,
        loan_date TEXT,
        current_date TEXT,
        total_months INTEGER,
        total_interest REAL,
        total_amount REAL,
        bond_path TEXT,
        details_entered_on TEXT,
        details_modified_on TEXT,
        status TEXT
    )''')
    # Repair derived values saved by older versions of the app.  The dates and
    # entered interest rate are preserved; only calculated fields are updated.
    rows = c.execute("SELECT id, principal_amount, interest, loan_date, current_date FROM loans").fetchall()
    for record_id, principal, interest, loan_date_value, current_date_value in rows:
        try:
            loan_date = parse_loan_date(loan_date_value)
            current_date = parse_loan_date(current_date_value)
            if current_date < loan_date:
                continue
            months = calculate_completed_months(loan_date, current_date)
            total_interest = float(principal) * float(interest) * months / 100
            c.execute("""UPDATE loans SET total_months=?, total_interest=?, total_amount=? WHERE id=?""",
                      (months, total_interest, float(principal) + total_interest, record_id))
        except (TypeError, ValueError):
            # Keep legacy rows with unrecognised dates unchanged.
            continue
    conn.commit()
    conn.close()
def export_to_pdf(data, filename="loan_export.pdf"):
    try:
        save_path = os.path.expanduser("~/Documents")
        if not os.path.exists(save_path):
            save_path = os.path.expanduser("~")

        full_path = os.path.join(save_path, filename)

        c = canvas.Canvas(full_path, pagesize=letter)
        width, height = letter

        y = height - 50
        for key, value in data.items():
            c.drawString(50, y, f"{key}: {value}")
            y -= 20

        c.save()
        print(f"PDF export successful: {full_path}")
        return full_path

    except Exception as e:
        print("PDF export failed:", e)
        return None

class HoverButton(Button):
    def __init__(self, **kwargs):
        self.normal_color = kwargs.pop("normal_color", (0.24, 0.45, 0.75, 1))
        self.hover_color = kwargs.pop(
            "hover_color",
            tuple(min(component + 0.12, 1) if index < 3 else component
                  for index, component in enumerate(self.normal_color)),
        )
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", self.normal_color)
        super().__init__(**kwargs)
        Window.bind(mouse_pos=self.on_mouse_pos)

    def on_mouse_pos(self, window, pos):
        if self.collide_point(*self.to_widget(*pos)):
            self.background_color = self.hover_color
        else:
            self.background_color = self.normal_color


class TableHeaderLabel(Label):
    """A coloured header cell used by the search-results table."""
    def __init__(self, **kwargs):
        kwargs.setdefault("color", (1, 1, 1, 1))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        with self.canvas.before:
            self._background_color = Color(0.12, 0.35, 0.65, 1)
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_background, size=self._update_background)

    def _update_background(self, _instance, _value):
        self._background.pos = self.pos
        self._background.size = self.size

class LoanForm(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.page = 0
        self.editing_id = None
        self.form_content = GridLayout(
            cols=1,
            size_hint_y=None,
            spacing=6,
            padding=8,
        )
        self.form_content.bind(minimum_height=self.form_content.setter("height"))

        # Larger text boxes
        self.name = TextInput(hint_text="Name", font_size=14, size_hint_y=None, height=35)
        self.mobile = TextInput(hint_text="Mobile", font_size=14, size_hint_y=None, height=35)
        self.address = TextInput(hint_text="Address", font_size=14, size_hint_y=None, height=35)
        self.reference = TextInput(hint_text="Reference", font_size=14, size_hint_y=None, height=35)
        self.additional_mobile = TextInput(hint_text="Additional Mobile", font_size=14, size_hint_y=None, height=35)
        self.comments = TextInput(hint_text="Comments", font_size=14, size_hint_y=None, height=35)
        self.bond_path_input = TextInput(
            hint_text="No bond file selected", font_size=12, readonly=True,
            size_hint_x=0.72,
        )
        self.bond_row = BoxLayout(size_hint_y=None, height=35, spacing=6)
        self.bond_row.add_widget(self.bond_path_input)
        self.bond_row.add_widget(HoverButton(
            text="Upload Bond", font_size=11, size_hint_x=0.28,
            normal_color=(0.60, 0.38, 0.10, 1), on_press=self.open_bond_chooser,
        ))
        self.principal = TextInput(hint_text="Principal Amount", font_size=14, size_hint_y=None, height=35)
        self.interest = TextInput(hint_text="Interest %", font_size=14, size_hint_y=None, height=35)
        self.loan_date = TextInput(hint_text="Loan Date (DD/MM/YYYY)", font_size=14, size_hint_y=None, height=35)
        self.current_date = TextInput(
            text=datetime.now().strftime("%d/%m/%Y"),
            hint_text="Current Date (DD/MM/YYYY)",
            font_size=14,
            size_hint_y=None,
            height=35,
        )
        self.total_months_input = TextInput(
            hint_text="Total Months (auto-calculated)",
            font_size=14,
            readonly=True,
            disabled=True,
            size_hint_y=None,
            height=35,
        )

        # Status dropdown
        self.status_spinner = Spinner(
            text="Select Status",
            values=("active", "closed", "hold"),
            size_hint_y=None,
            height=35
        )
        self.status_row = BoxLayout(size_hint_y=None, height=35, spacing=6)
        self.status_row.add_widget(Label(text="Status", size_hint_x=0.3))
        self.status_row.add_widget(self.status_spinner)

        for widget in [self.name, self.mobile, self.address, self.reference,
                       self.additional_mobile, self.comments, self.bond_row, self.principal, self.interest,
                       self.loan_date, self.current_date, self.total_months_input, self.status_row]:
            self.form_content.add_widget(widget)

        self.loan_date.bind(text=self.update_total_months)
        self.current_date.bind(text=self.update_total_months)

        # Keep all primary actions visible together in one row.
        action_box = GridLayout(cols=6, size_hint_y=None, height=40, spacing=3)
        action_box.add_widget(HoverButton(text="Save", font_size=11, normal_color=(0.16, 0.55, 0.32, 1), on_press=self.save_record))
        action_box.add_widget(HoverButton(text="Search", font_size=11, normal_color=(0.12, 0.42, 0.78, 1), on_press=self.search_record))
        action_box.add_widget(HoverButton(text="All CSV", font_size=11, normal_color=(0.04, 0.55, 0.55, 1), on_press=self.export_all_records_csv))
        action_box.add_widget(HoverButton(text="Excel", font_size=11, normal_color=(0.10, 0.45, 0.22, 1), on_press=self.export_excel))
        action_box.add_widget(HoverButton(text="Import", font_size=11, normal_color=(0.48, 0.28, 0.68, 1), on_press=self.open_import_popup))
        action_box.add_widget(HoverButton(text="PDF", font_size=11, normal_color=(0.82, 0.35, 0.10, 1), on_press=self.export_pdf))
        self.form_content.add_widget(action_box)

        # Results area
        self.results = GridLayout(cols=1, size_hint=(None, None), width=880)
        self.results.bind(minimum_height=self.results.setter('height'))
        self.results_scroll = ScrollView(
            size_hint_y=None,
            height=200,
            scroll_type=["bars", "content"],
            bar_width=10,
            bar_color=(0.35, 0.35, 0.35, 1),
            do_scroll_x=True,
            do_scroll_y=True,
        )
        self.results_scroll.add_widget(self.results)
        self.form_content.add_widget(self.results_scroll)

        # Pagination controls
        nav_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=40)
        nav_box.add_widget(HoverButton(text="Previous", normal_color=(0.38, 0.32, 0.68, 1), on_press=self.prev_page))
        nav_box.add_widget(HoverButton(text="Next", normal_color=(0.38, 0.32, 0.68, 1), on_press=self.next_page))
        self.form_content.add_widget(nav_box)

        self.form_scroll = ScrollView(
            size_hint=(1, 1),
            scroll_type=["bars", "content"],
            bar_width=10,
            bar_color=(0.35, 0.35, 0.35, 1),
        )
        self.form_scroll.add_widget(self.form_content)
        self.add_widget(self.form_scroll)

    def save_record(self, instance):
        required_fields = {
            "Name": self.name,
            "Mobile": self.mobile,
            "Address": self.address,
            "Reference": self.reference,
            "Additional Mobile": self.additional_mobile,
            "Comments": self.comments,
            "Principal Amount": self.principal,
            "Interest %": self.interest,
            "Loan Date": self.loan_date,
            "Current Date": self.current_date,
        }
        missing_fields = [name for name, widget in required_fields.items() if not widget.text.strip()]
        if missing_fields:
            self.show_message("Please enter: " + ", ".join(missing_fields) + ".")
            return

        if self.status_spinner.text not in self.status_spinner.values:
            self.show_message("Select a Status before saving.")
            return

        try:
            principal = float(self.principal.text.strip())
            interest = float(self.interest.text.strip())
        except ValueError:
            self.show_message("Enter valid numbers for Principal Amount and Interest %.")
            return

        if principal < 0 or interest < 0:
            self.show_message("Principal Amount and Interest % cannot be negative.")
            return

        try:
            loan_date = datetime.strptime(self.loan_date.text.strip(), "%d/%m/%Y").date()
            current_date = datetime.strptime(self.current_date.text.strip(), "%d/%m/%Y").date()
        except ValueError:
            self.show_message("Enter Loan Date and Current Date in DD/MM/YYYY format.")
            return

        if current_date < loan_date:
            self.show_message("Current Date cannot be earlier than Loan Date.")
            return

        months = self.calculate_total_months(loan_date, current_date)
        self.total_months_input.text = str(months)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_interest = principal * interest * months / 100
        total_amount = principal + total_interest
        status_val = self.status_spinner.text

        if self.editing_id:
            c.execute('''UPDATE loans SET
                name=?, mobile=?, address=?, reference=?, additional_mobile=?, comments=?,
                principal_amount=?, interest=?, loan_date=?, current_date=?, details_modified_on=?, total_months=?, total_interest=?, total_amount=?, bond_path=?, status=?
                WHERE id=?''',
                (self.name.text, self.mobile.text, self.address.text, self.reference.text,
                 self.additional_mobile.text, self.comments.text, principal, interest,
                 self.loan_date.text.strip(), self.current_date.text.strip(), now, months,
                 total_interest, total_amount, self.bond_path_input.text.strip(), status_val, self.editing_id))
            success_message = "Record updated successfully."
            self.editing_id = None
        else:
            c.execute('''INSERT INTO loans 
                (name, mobile, address, reference, additional_mobile, comments,
                 principal_amount, interest, loan_date, current_date, total_months,
                 total_interest, total_amount, bond_path, details_entered_on, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (self.name.text, self.mobile.text, self.address.text,
                 self.reference.text, self.additional_mobile.text, self.comments.text,
                 principal, interest, self.loan_date.text.strip(), self.current_date.text.strip(), months, total_interest, total_amount,
                 self.bond_path_input.text.strip(), now, status_val))
            success_message = "Record saved successfully."
        conn.commit()
        conn.close()
        self.show_message(success_message)

    def open_bond_chooser(self, instance):
        """Choose a supported bond file while creating or editing a loan."""
        content = BoxLayout(orientation="vertical", padding=8, spacing=8)
        chooser = FileChooserListView(
            path=os.path.expanduser("~"),
            filters=["*.jpg", "*.jpeg", "*.png", "*.pdf", "*.JPG", "*.JPEG", "*.PNG", "*.PDF"],
        )
        buttons = BoxLayout(size_hint_y=None, height=42, spacing=8)
        select_button = Button(text="Upload selected file")
        cancel_button = Button(text="Cancel")
        buttons.add_widget(select_button)
        buttons.add_widget(cancel_button)
        content.add_widget(chooser)
        content.add_widget(buttons)
        popup = Popup(title="Upload bond (JPG, PNG, or PDF)", content=content,
                      size_hint=(0.95, 0.9), auto_dismiss=False)
        select_button.bind(on_press=lambda _button: self.save_bond_file(chooser.selection, popup))
        cancel_button.bind(on_press=popup.dismiss)
        popup.open()

    def save_bond_file(self, selection, chooser_popup):
        """Copy the selected bond into the app folder and remember its saved path."""
        if not selection:
            self.show_message("Choose a JPG, PNG, or PDF bond file first.")
            return
        source_path = selection[0]
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in (".jpg", ".jpeg", ".png", ".pdf"):
            self.show_message("Bond file must be a JPG, PNG, or PDF.")
            return
        try:
            bond_directory = os.path.join(os.path.dirname(os.path.abspath(DB_NAME)), "bond_files")
            os.makedirs(bond_directory, exist_ok=True)
            record_part = self.editing_id if self.editing_id else "new"
            filename = f"bond_{record_part}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
            saved_path = os.path.join(bond_directory, filename)
            shutil.copy2(source_path, saved_path)
        except OSError as error:
            self.show_message(f"Could not upload bond file: {error}")
            return
        self.bond_path_input.text = saved_path
        chooser_popup.dismiss()
        self.show_message("Bond file uploaded. Click Save to attach it to this record.")

    @staticmethod
    def calculate_total_months(loan_date, current_date):
        """Return completed calendar months between the two dates."""
        return calculate_completed_months(loan_date, current_date)

    @staticmethod
    def format_date_for_input(value):
        """Convert existing database date values to the form format."""
        try:
            return parse_loan_date(value).strftime("%d/%m/%Y")
        except ValueError:
            return value

    @staticmethod
    def normalize_status(value):
        """Return a status value supported by the status selector."""
        status = str(value or "active").strip().lower()
        return status if status in ("active", "closed", "hold") else "active"

    def update_total_months(self, instance, value):
        """Update the read-only Total Months field when either date changes."""
        try:
            loan_date = datetime.strptime(self.loan_date.text.strip(), "%d/%m/%Y").date()
            current_date = datetime.strptime(self.current_date.text.strip(), "%d/%m/%Y").date()
            if current_date >= loan_date:
                self.total_months_input.text = str(self.calculate_total_months(loan_date, current_date))
            else:
                self.total_months_input.text = ""
        except ValueError:
            self.total_months_input.text = ""

    def search_record(self, instance, reset_page=True):
        name = self.name.text.strip()
        mobile = self.mobile.text.strip()
        comments = self.comments.text.strip()

        if not any((name, mobile, comments)):
            self.show_message("Enter at least a Name, Mobile, or Comment to search.")
            return

        if reset_page:
            self.page = 0

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        offset = self.page * 10
        c.execute("""SELECT id, name, mobile, address, reference, additional_mobile, comments,
                            principal_amount, interest, loan_date, current_date, total_months,
                            total_interest, total_amount, status, bond_path
                     FROM loans WHERE name LIKE ? OR mobile LIKE ? OR comments LIKE ?
                     LIMIT 10 OFFSET ?""",
                  (f"%{name}%", f"%{mobile}%", f"%{comments}%", offset))
        rows = c.fetchall()
        conn.close()

        self.results.clear_widgets()
        column_definitions = (
            ("ID", 40), ("Name", 90), ("Mobile", 85), ("Principal", 90),
            ("Loan Date", 85), ("Months", 55), ("Interest %", 70),
            ("Total Interest", 95), ("Total Amount", 100), ("Status", 65),
        )
        header_box = BoxLayout(
            orientation="horizontal", size_hint=(None, None), width=880, height=32
        )
        for heading, width in column_definitions:
            header_box.add_widget(TableHeaderLabel(
                text=heading, size_hint_x=None, width=width, font_size=10,
                text_size=(width, 32),
            ))
        header_box.add_widget(TableHeaderLabel(text="Bond", size_hint_x=None, width=35,
                                                font_size=10, text_size=(35, 32)))
        header_box.add_widget(TableHeaderLabel(text="Edit", size_hint_x=None, width=35,
                                                font_size=10, text_size=(35, 32)))
        header_box.add_widget(TableHeaderLabel(text="Delete", size_hint_x=None, width=35,
                                                font_size=10, text_size=(35, 32)))
        self.results.add_widget(header_box)
        for row in rows:
            status = self.normalize_status(row[14])
            record_box = BoxLayout(orientation="horizontal", size_hint=(None, None), width=880, height=30)
            values = (
                row[0], row[1], row[2], f"{row[7]:.2f}", row[9], row[11],
                f"{row[8]:.2f}", f"{row[12]:.2f}", f"{row[13]:.2f}", status,
            )
            for value, (_heading, width) in zip(values, column_definitions):
                record_box.add_widget(Label(
                    text=str(value), size_hint_x=None, width=width, font_size=11,
                    halign="left", valign="middle", text_size=(width - 6, 30),
                ))
            record_box.add_widget(HoverButton(
                text="B", size_hint_x=None, width=35, normal_color=(0.60, 0.38, 0.10, 1),
                on_press=lambda inst, path=row[15], record_id=row[0]: self.show_bond_image(path, record_id),
            ))
            record_box.add_widget(HoverButton(text="E", size_hint_x=None, width=35, normal_color=(0.18, 0.50, 0.82, 1), on_press=lambda inst, r=row: self.load_record(r)))
            record_box.add_widget(HoverButton(text="D", size_hint_x=None, width=35, normal_color=(0.78, 0.20, 0.20, 1), on_press=lambda inst, rid=row[0]: self.delete_record(rid)))
            self.results.add_widget(record_box)

    def show_bond_image(self, bond_path, record_id):
        """Open the saved bond image for a record in a closable popup."""
        if not bond_path:
            self.show_message(f"No bond image is saved for record {record_id}.")
            return

        image_path = os.path.abspath(os.path.expanduser(str(bond_path)))
        if not os.path.isfile(image_path):
            self.show_message(f"Bond image for record {record_id} was not found:\n{image_path}")
            return

        content = BoxLayout(orientation="vertical", padding=8, spacing=8)
        if image_path.lower().endswith(".pdf"):
            content.add_widget(Label(
                text=f"A PDF bond is attached to record {record_id}.\n\n{image_path}\n\n"
                     "PDF preview is not available in the app.",
                halign="center", valign="middle",
            ))
        else:
            content.add_widget(Image(source=image_path, allow_stretch=True, keep_ratio=True))
        close_button = Button(text="Close", size_hint_y=None, height=42)
        content.add_widget(close_button)
        popup = Popup(
            title=f"Bond image - Record {record_id}", content=content,
            size_hint=(0.95, 0.9), auto_dismiss=False,
        )
        close_button.bind(on_press=popup.dismiss)
        popup.open()

    def load_record(self, row):
        self.editing_id = row[0]
        self.name.text = row[1]
        self.mobile.text = row[2]
        self.address.text = row[3]
        self.reference.text = row[4]
        self.additional_mobile.text = row[5]
        self.comments.text = row[6]
        self.bond_path_input.text = row[15] or ""
        self.principal.text = str(row[7])
        self.interest.text = str(row[8])
        self.loan_date.text = self.format_date_for_input(row[9])
        self.current_date.text = self.format_date_for_input(row[10])
        self.total_months_input.text = str(row[11])
        self.status_spinner.text = self.normalize_status(row[14])
        self.show_message(f"Editing record {row[0]}")

    def delete_record(self, record_id):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("DELETE FROM loans WHERE id=?", (record_id,))
        conn.commit()
        conn.close()
        self.show_message(f"Deleted record {record_id}")

    def export_csv(self, instance):
        self.export_all_records_csv(instance)

    def export_all_records_csv(self, instance):
        """Export every saved loan as one row in a CSV file."""
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM loans", conn)
        df.to_csv("loans_export.csv", index=False)
        conn.close()
        self.show_message(f"Exported {len(df)} record(s) to loans_export.csv")

    def export_excel(self, instance):
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM loans", conn)
        df.to_excel("loans_export.xlsx", index=False)
        conn.close()
        self.show_message("Exported to loans_export.xlsx")

    def open_import_popup(self, instance):
        """Let the user choose a CSV or Excel file to import."""
        content = BoxLayout(orientation="vertical", padding=8, spacing=8)
        chooser = FileChooserListView(
            path=os.path.expanduser("~"),
            filters=["*.csv", "*.xlsx", "*.xls"],
        )
        buttons = BoxLayout(size_hint_y=None, height=42, spacing=8)
        import_button = Button(text="Import selected file")
        cancel_button = Button(text="Cancel")
        buttons.add_widget(import_button)
        buttons.add_widget(cancel_button)
        content.add_widget(chooser)
        content.add_widget(buttons)
        popup = Popup(title="Import loans (CSV or Excel)", content=content,
                      size_hint=(0.95, 0.9), auto_dismiss=False)
        import_button.bind(on_press=lambda _button: self.import_selected_file(chooser.selection, popup))
        cancel_button.bind(on_press=popup.dismiss)
        popup.open()

    @staticmethod
    def _import_value(value):
        """Convert spreadsheet cells to clean strings, including empty cells."""
        if pd.isna(value):
            return ""
        return str(value).strip()

    @staticmethod
    def _normalise_column_name(name):
        return "".join(character for character in str(name).lower() if character.isalnum())

    def import_selected_file(self, selection, chooser_popup):
        if not selection:
            self.show_message("Choose a CSV or Excel file first.")
            return
        chooser_popup.dismiss()
        self.import_records(selection[0])

    def import_records(self, file_path):
        """Import valid rows and show a detailed success/error report."""
        try:
            extension = os.path.splitext(file_path)[1].lower()
            if extension == ".csv":
                dataframe = pd.read_csv(file_path, dtype=str, keep_default_na=False)
            elif extension in (".xlsx", ".xls"):
                dataframe = pd.read_excel(file_path, dtype=str, keep_default_na=False)
            else:
                raise ValueError("Only CSV, XLSX, and XLS files are supported.")
        except Exception as error:
            self.show_import_report([], [("File", f"Could not read file: {error}")])
            return

        # Accept both the app's exported column names and friendly spreadsheet headings.
        aliases = {
            "name": "name", "mobile": "mobile", "address": "address",
            "reference": "reference", "additionalmobile": "additional_mobile",
            "comments": "comments", "principalamount": "principal_amount",
            "interest": "interest", "loandate": "loan_date",
            "currentdate": "current_date", "status": "status",
        }
        columns = {self._normalise_column_name(column): column for column in dataframe.columns}
        missing = [field for field in ("name", "mobile", "address", "reference", "additional_mobile",
                                       "comments", "principal_amount", "interest", "loan_date", "current_date", "status")
                   if field not in aliases.values() or not any(aliases.get(key) == field for key in columns)]
        if missing:
            self.show_import_report([], [("File", "Missing required columns: " + ", ".join(missing))])
            return

        successful, failed = [], []
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            for index, row in dataframe.iterrows():
                row_number = index + 2  # Header is row 1 in the source file.
                values = {field: self._import_value(row[columns[key]])
                          for key, field in aliases.items() if key in columns}
                try:
                    required = ("name", "mobile", "address", "reference", "additional_mobile", "comments",
                                "principal_amount", "interest", "loan_date", "current_date")
                    empty = [field.replace("_", " ") for field in required if not values[field]]
                    if empty:
                        raise ValueError("Missing " + ", ".join(empty))
                    principal, interest = float(values["principal_amount"]), float(values["interest"])
                    if principal < 0 or interest < 0:
                        raise ValueError("Principal Amount and Interest % cannot be negative")
                    loan_date = parse_loan_date(values["loan_date"])
                    current_date = parse_loan_date(values["current_date"])
                    if current_date < loan_date:
                        raise ValueError("Current Date cannot be earlier than Loan Date")
                    values["loan_date"] = loan_date.strftime("%d/%m/%Y")
                    values["current_date"] = current_date.strftime("%d/%m/%Y")
                    status = self.normalize_status(values["status"])
                    if values["status"].lower() not in ("active", "closed", "hold"):
                        raise ValueError("Status must be active, closed, or hold")
                    months = self.calculate_total_months(loan_date, current_date)
                    total_interest = principal * interest * months / 100
                    cursor.execute('''INSERT INTO loans (name, mobile, address, reference, additional_mobile, comments,
                                   principal_amount, interest, loan_date, current_date, total_months, total_interest,
                                   total_amount, details_entered_on, status)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                   (values["name"], values["mobile"], values["address"], values["reference"],
                                    values["additional_mobile"], values["comments"], principal, interest,
                                    values["loan_date"], values["current_date"], months, total_interest,
                                    principal + total_interest, now, status))
                    successful.append((row_number, values["name"], values["mobile"]))
                except Exception as error:
                    failed.append((f"Row {row_number}", str(error)))
            conn.commit()
        except sqlite3.Error as error:
            conn.rollback()
            failed.append(("Database", str(error)))
            successful = []
        finally:
            conn.close()
        self.show_import_report(successful, failed)

    def show_import_report(self, successful, failed):
        """Show every imported and rejected record in a scrollable popup."""
        lines = [f"Imported successfully: {len(successful)}", f"Errors: {len(failed)}", ""]
        lines.append("SUCCESSFUL RECORDS")
        lines.extend(f"Row {row}: {name} ({mobile})" for row, name, mobile in successful) if successful else lines.append("None")
        lines.extend(["", "ERROR RECORDS"])
        lines.extend(f"{location}: {reason}" for location, reason in failed) if failed else lines.append("None")
        report = "\n".join(lines)
        content = BoxLayout(orientation="vertical", padding=10, spacing=8)
        scroll = ScrollView()
        label = Label(text=report, size_hint_y=None, halign="left", valign="top")
        label.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
        label.bind(texture_size=lambda widget, size: setattr(widget, "height", size[1] + 10))
        scroll.add_widget(label)
        close_button = Button(text="Close", size_hint_y=None, height=42)
        content.add_widget(scroll)
        content.add_widget(close_button)
        popup = Popup(title="Import results", content=content, size_hint=(0.9, 0.8), auto_dismiss=False)
        close_button.bind(on_press=popup.dismiss)
        popup.open()

    def export_pdf(self, instance):
        data = {
            "Name": self.name.text,
            "Mobile": self.mobile.text,
            "Address": self.address.text,
            "Reference": self.reference.text,
            "Additional Mobile": self.additional_mobile.text,
            "Comments": self.comments.text,
            "Principal Amount": self.principal.text,
            "Interest": self.interest.text,
            "Loan Date": self.loan_date.text,
            "Current Date": self.current_date.text,
            "Total Months": self.total_months_input.text,
            "Status": self.status_spinner.text
        }
        if export_to_pdf(data, filename="loans_export.pdf"):
            self.show_message("Exported to loans_export.pdf")

    def prev_page(self, instance):
        """Show the previous results page, when one exists."""
        if self.page > 0:
            self.page -= 1
        self.search_record(instance, reset_page=False)

    def next_page(self, instance):
        """Show the next results page."""
        self.page += 1
        self.search_record(instance, reset_page=False)

    def show_message(self, message):
        """Display a status or validation message in the application."""
        print(message)
        content = BoxLayout(orientation="vertical", padding=12, spacing=12)
        content.add_widget(Label(text=message))
        close_button = Button(text="Close", size_hint_y=None, height=40)
        content.add_widget(close_button)

        popup = Popup(
            title="Loan App",
            content=content,
            size_hint=(0.8, None),
            height=180,
            auto_dismiss=False,
        )
        close_button.bind(on_press=popup.dismiss)
        popup.open()

class LoanApp(App):
    def build(self):
        init_db()
        return LoanForm()

if __name__ == "__main__":
    LoanApp().run()
