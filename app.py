from flask import Flask, request, session, redirect
import csv
import os
from datetime import datetime, time, timedelta

from twilio.rest import Client

app = Flask(__name__)
app.secret_key = os.getenv("DOCKFLOW_SECRET", "dev-secret-change-me")

def is_admin():
    return session.get("admin") == True

def require_admin():
    if not is_admin():
        return redirect("/login")
    return None

CSV_FILE = "citas.csv"

DOCKS = ["Dock 1", "Dock 2", "Dock 3", "Dock 4", "Dock 5"]

# Horario A: 08:00 a 17:00 cada 30 min
START_TIME = time(8, 0)
END_TIME = time(17, 0)
STEP_MIN = 30

def docks_options_html(selected=None):
    out = []
    for d in DOCKS:
        sel = "selected" if selected == d else ""
        out.append(f"<option value='{d}' {sel}>{d}</option>")
    return "\n".join(out)

def generar_slots():
    """Retorna lista de strings HH:MM desde START_TIME hasta END_TIME (incluye 17:00)."""
    slots = []
    dt = datetime(2000, 1, 1, START_TIME.hour, START_TIME.minute)
    end_dt = datetime(2000, 1, 1, END_TIME.hour, END_TIME.minute)
    while dt <= end_dt:
        slots.append(dt.strftime("%H:%M"))
        dt += timedelta(minutes=STEP_MIN)
    return slots

SLOTS = generar_slots()

def slot_ocupado(fecha, hora, dock):
    if not os.path.exists(CSV_FILE):
        return False

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for r in reader:
            if not r:
                continue

            # header
            if str(r[0]).lower().strip() in ["timestamp", "ts", "time"]:
                continue

            # nuevo con status: ts, empresa, chofer, telefono, dock, fecha, hora, status
            if len(r) >= 8:
                r_dock = (r[4] or "").strip()
                r_fecha = (r[5] or "").strip()
                r_hora = (r[6] or "").strip()
                r_status = (r[7] or "ACTIVE").strip().upper()
            # nuevo sin status (compatibilidad): ts, empresa, chofer, telefono, dock, fecha, hora
            elif len(r) >= 7:
                r_dock = (r[4] or "").strip()
                r_fecha = (r[5] or "").strip()
                r_hora = (r[6] or "").strip()
                r_status = "ACTIVE"
            # viejo: ts, empresa, chofer, telefono, fecha, hora
            elif len(r) >= 6:
                r_dock = "Dock 1"
                r_fecha = (r[4] or "").strip()
                r_hora = (r[5] or "").strip()
                r_status = "ACTIVE"
            else:
                continue

            if r_status == "CANCELLED":
                continue

            if r_fecha == fecha and r_hora == hora and r_dock == dock:
                return True

    return False


def horas_disponibles(fecha, dock):
    libres = []
    for h in SLOTS:
        if not slot_ocupado(fecha, h, dock):
            libres.append(h)
    return libres

def guardar_cita(row):
    existe = os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not existe:
            w.writerow(["timestamp","empresa","chofer","telefono","dock","fecha","hora","status"])
        w.writerow(row)

def make_id(ts, dock, fecha, hora):
    return f"{ts}|{dock}|{fecha}|{hora}"

def leer_citas():
    citas = []
    if not os.path.exists(CSV_FILE):
        return citas

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for r in reader:
            if not r:
                continue

            if str(r[0]).lower().strip() in ["timestamp", "ts", "time"]:
                continue

            if len(r) >= 8:
                ts, empresa, chofer, telefono, dock, fecha, hora, status = r[:8]
            elif len(r) >= 7:
                ts, empresa, chofer, telefono, dock, fecha, hora = r[:7]
                status = "ACTIVE"
            elif len(r) >= 6:
                ts, empresa, chofer, telefono, fecha, hora = r[:6]
                dock = "Dock 1"
                status = "ACTIVE"
            else:
                continue

            ts = (ts or "").strip()
            dock = (dock or "").strip()
            fecha = (fecha or "").strip()
            hora = (hora or "").strip()
            status = (status or "ACTIVE").strip().upper()

            citas.append({
                "id": make_id(ts, dock, fecha, hora),
                "timestamp": ts,
                "empresa": (empresa or "").strip(),
                "chofer": (chofer or "").strip(),
                "telefono": (telefono or "").strip(),
                "dock": dock,
                "fecha": fecha,
                "hora": hora,
                "status": status
            })

    citas.sort(key=lambda x: (x["fecha"], x["hora"], x["dock"]))
    return citas


def enviar_sms(destino, mensaje):
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")

    if not sid or not token or not from_number:
        print("⚠️ Twilio no configurado. SMS SIMULADO:")
        print("TO:", destino)
        print("MSG:", mensaje)
        return False

    try:
        client = Client(sid, token)
        msg = client.messages.create(body=mensaje, from_=from_number, to=destino)
        print("✅ SMS enviado:", msg.sid)
        return True
    except Exception as e:
        print("⚠️ SMS NO enviado (Twilio pending o error):", e)
        print("SMS SIMULADO ->", destino, mensaje)
        return False

@app.get("/")
def home():
    return f"""
    <h2>Dockflow - Solicitar cita</h2>
    <form method='POST' action='/horas'>
      Empresa:<br><input name='empresa' required><br><br>
      Chofer:<br><input name='chofer' required><br><br>
      Teléfono (+1...):<br><input name='telefono' required placeholder="+17000000000"><br><br>

      Dock:<br>
      <select name='dock' required>
        {docks_options_html()}
      </select><br><br>

      Fecha:<br><input type='date' name='fecha' required><br><br>

      <button type='submit'>Ver horas disponibles</button>
    </form>
    <p style="color:gray;">Horario: 08:00 - 17:00 (cada 30 min)</p>
    """

@app.post("/horas")
def ver_horas():
    empresa = request.form["empresa"].strip()
    chofer = request.form["chofer"].strip()
    telefono = request.form["telefono"].strip()
    dock = request.form["dock"].strip()
    fecha = request.form["fecha"].strip()

    libres = horas_disponibles(fecha, dock)

    if not libres:
        return f"""
        <h2>❌ No hay horas disponibles</h2>
        <p>No hay slots libres para <b>{dock}</b> el <b>{fecha}</b>.</p>
        <a href="/">Volver</a>
        """

    options = "\n".join([f"<option value='{h}'>{h}</option>" for h in libres])

    # Pasamos los datos escondidos (hidden inputs) para confirmar
    return f"""
    <h2>Selecciona una hora disponible</h2>
    <p><b>Dock:</b> {dock} | <b>Fecha:</b> {fecha}</p>

    <form method='POST' action='/agendar'>
      <input type='hidden' name='empresa' value="{empresa}">
      <input type='hidden' name='chofer' value="{chofer}">
      <input type='hidden' name='telefono' value="{telefono}">
      <input type='hidden' name='dock' value="{dock}">
      <input type='hidden' name='fecha' value="{fecha}">

      Hora:<br>
      <select name='hora' required>
        {options}
      </select><br><br>

      <button type='submit'>Confirmar cita</button>
    </form>

    <br><a href="/">← Cambiar datos</a>
    """

@app.post("/agendar")
def agendar():
    empresa = request.form["empresa"].strip()
    chofer = request.form["chofer"].strip()
    telefono = request.form["telefono"].strip()
    dock = request.form["dock"].strip()
    fecha = request.form["fecha"].strip()
    hora = request.form["hora"].strip()

    # Protección extra por si 2 personas eligen el mismo slot al mismo tiempo
    if slot_ocupado(fecha, hora, dock):
        return f"""
        <h2>❌ Hora ocupada</h2>
        <p>Ese slot se acaba de ocupar: <b>{dock}</b> {fecha} {hora}</p>
        <a href="/">Volver</a>
        """

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    guardar_cita([ts, empresa, chofer, telefono, dock, fecha, hora, "ACTIVE"])


    sms = f"Dockflow: Cita confirmada ({dock}) para {fecha} a las {hora}. Reply STOP to opt out."
    enviar_sms(telefono, sms)

    return f"""
    <h2>✅ Cita confirmada</h2>
    <p><b>Empresa:</b> {empresa}</p>
    <p><b>Chofer:</b> {chofer}</p>
    <p><b>Teléfono:</b> {telefono}</p>
    <p><b>Dock:</b> {dock}</p>
    <p><b>Fecha:</b> {fecha}</p>
    <p><b>Hora:</b> {hora}</p>
    <a href="/">Nueva cita</a>
    """
@app.get("/login")
def login_form():
    return """
    <h2>🔐 Dockflow Admin Login</h2>
    <form method="POST" action="/login">
      Password:<br>
      <input type="password" name="password" required>
      <br><br>
      <button type="submit">Login</button>
    </form>
    """

@app.post("/login")
def login_post():
    admin_pass = os.getenv("DOCKFLOW_ADMIN_PASS", "")
    pw = request.form.get("password", "")

    if admin_pass and pw == admin_pass:
        session["admin"] = True
        return redirect("/admin")

    return """
    <h2>❌ Wrong password</h2>
    <a href="/login">Try again</a>
    """

@app.get("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/login")

@app.get("/admin")
def admin():
    guard = require_admin()
    if guard:
        return guard

    # filtro opcional: /admin?date=YYYY-MM-DD
    selected_date = request.args.get("date", "").strip()

    citas = leer_citas()
    if selected_date:
        citas = [c for c in citas if c["fecha"] == selected_date]

    # mini formulario de filtro
    filter_html = f"""
    <form method="GET" action="/admin" style="margin-bottom:12px;">
      <label><b>Filtrar por fecha:</b></label>
      <input type="date" name="date" value="{selected_date}">
      <button type="submit">Filter</button>
      <a href="/admin" style="margin-left:8px;">Clear</a>
    </form>
    """

    rows = ""
    for c in citas:
        cancel_btn = ""
        if c["status"] != "CANCELLED":
            cancel_btn = f"""
            <form method="POST" action="/cancelar" style="margin:0;">
              <input type="hidden" name="id" value="{c['id']}">
              <button type="submit">Cancel</button>
            </form>
            """
        else:
            cancel_btn = "<span style='color:gray;'>Cancelled</span>"

        rows += f"""
        <tr>
          <td>{c['fecha']}</td>
          <td>{c['hora']}</td>
          <td>{c['dock']}</td>
          <td>{c['empresa']}</td>
          <td>{c['chofer']}</td>
          <td>{c['telefono']}</td>
          <td>{c['status']}</td>
          <td>{cancel_btn}</td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='8' style='color:gray;'>No hay citas para esta fecha.</td></tr>"

    return f"""
    <h2>📋 Dockflow – Panel Admin</h2>
    {filter_html}
    <table border="1" cellpadding="6" cellspacing="0">
      <tr>
        <th>Fecha</th>
        <th>Hora</th>
        <th>Dock</th>
        <th>Empresa</th>
        <th>Chofer</th>
        <th>Teléfono</th>
        <th>Status</th>
        <th>Action</th>
      </tr>
      {rows}
    </table>

    <br>
    <a href="/">← Volver al formulario</a>
    """

def cancelar_por_id(cita_id):
    if not os.path.exists(CSV_FILE):
        return False

    rows = []
    found = False

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    new_rows = []
    for r in rows:
        if not r:
            continue

        # header - lo dejamos igual
        if str(r[0]).lower().strip() in ["timestamp", "ts", "time"]:
            # si el header viejo no tiene status, lo expandimos
            header = r
            if len(header) < 8:
                header = ["timestamp","empresa","chofer","telefono","dock","fecha","hora","status"]
            new_rows.append(header)
            continue

        # normaliza a 8 columnas
        if len(r) >= 8:
            ts, empresa, chofer, telefono, dock, fecha, hora, status = r[:8]
        elif len(r) >= 7:
            ts, empresa, chofer, telefono, dock, fecha, hora = r[:7]
            status = "ACTIVE"
        elif len(r) >= 6:
            ts, empresa, chofer, telefono, fecha, hora = r[:6]
            dock = "Dock 1"
            status = "ACTIVE"
        else:
            new_rows.append(r)
            continue

        _id = make_id((ts or "").strip(), (dock or "").strip(), (fecha or "").strip(), (hora or "").strip())

        if _id == cita_id:
            status = "CANCELLED"
            found = True

        new_rows.append([ (ts or "").strip(), (empresa or "").strip(), (chofer or "").strip(),
                          (telefono or "").strip(), (dock or "").strip(), (fecha or "").strip(),
                          (hora or "").strip(), (status or "ACTIVE").strip().upper() ])

    if found:
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(new_rows)

    return found

@app.post("/cancelar")
def cancelar():
    guard = require_admin()
    if guard:
        return guard

    cita_id = request.form.get("id", "").strip()
    ok = cancelar_por_id(cita_id)
    return f"""
    <h2>{'✅ Cita cancelada' if ok else '❌ No se encontró la cita'}</h2>
    <a href="/admin">Volver al panel</a>
    """

if __name__ == "__main__":
    app.run(debug=True)
