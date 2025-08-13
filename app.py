#!/usr/bin/env python3
"""
Aplicación web para registrar horas de trabajo utilizando únicamente las
bibliotecas estándar de Python. Este servidor implementa las mismas
funcionalidades que una aplicación con un framework, pero sin depender de
paquetes externos como Flask. Permite iniciar y detener un cronómetro,
registrar horas manualmente, cancelar horas adicionales o faltantes, ver
registros agrupados por día y configurar la cantidad máxima de horas
diarias. Está pensado para ser liviano y ejecutarse en segundo plano en
equipos con Windows u otros sistemas.

Para ejecutar este servidor, simplemente ejecuta este archivo con Python:

    python3 app.py

Luego accede a http://localhost:8000 en tu navegador.

Los comentarios en español están incluidos para facilitar la comprensión
y eventual modificación del código.
"""

import os
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote_plus
from datetime import datetime, date, timedelta
import json
import random

# Directorio base del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

PALETA_COLORES = [
    '#e6194B', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4',
    '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff',
    '#9A6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1',
    '#000075', '#808080'
]

# Nombres de los días para mapear columnas de máximo por día
DIAS_SEMANA = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']


def color_aleatorio() -> str:
    return random.choice(PALETA_COLORES)


def obtener_conexion():
    """Devuelve una conexión a la base de datos SQLite con filas como dicts."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db():
    """Crea las tablas necesarias si no existen y asigna valores por defecto."""
    conn = obtener_conexion()
    cur = conn.cursor()
    # Tabla de registros
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            inicio TEXT,
            fin TEXT,
            duracion INTEGER NOT NULL,
            descripcion TEXT,
            manual INTEGER NOT NULL DEFAULT 0
        )'''
    )
    # Tabla de configuración
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )'''
    )
    # Tabla de tags
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            color TEXT NOT NULL,
            max_diario INTEGER NOT NULL DEFAULT 0
        )'''
    )
    # Añade columnas de máximos por día si no existen
    for dia in DIAS_SEMANA:
        try:
            cur.execute(f'ALTER TABLE tags ADD COLUMN max_{dia} INTEGER NOT NULL DEFAULT 0')
        except sqlite3.OperationalError:
            pass
    # Tabla relación registro-tags
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS registro_tags (
            registro_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            UNIQUE (registro_id, tag_id),
            FOREIGN KEY(registro_id) REFERENCES registros(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )'''
    )
    # Valor por defecto de horas máximas diarias: 7h 30m = 450 minutos
    cur.execute('INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)',
                ('horas_max_diarias', str(450)))
    conn.commit()
    conn.close()


def obtener_horas_maximas():
    """Obtiene la cantidad de minutos máximos permitidos al día."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute('SELECT valor FROM config WHERE clave = ?', ('horas_max_diarias',))
    row = cur.fetchone()
    conn.close()
    return int(row['valor']) if row else 0


def actualizar_horas_maximas(minutos: int) -> None:
    """Actualiza la configuración de minutos máximos diarios."""
    conn = obtener_conexion()
    conn.execute('UPDATE config SET valor = ? WHERE clave = ?', (str(minutos), 'horas_max_diarias'))
    conn.commit()
    conn.close()


def obtener_tags():
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute('SELECT * FROM tags ORDER BY nombre')
    rows = cur.fetchall()
    conn.close()
    return rows


def crear_tag(nombre: str, max_por_dia=None) -> int:
    """Crea un tag con un color aleatorio y límites por día."""
    if max_por_dia is None:
        max_por_dia = [0] * 7
    conn = obtener_conexion()
    cur = conn.cursor()
    color = color_aleatorio()
    cur.execute(
        'INSERT INTO tags (nombre, color, max_diario, max_lunes, max_martes, max_miercoles, max_jueves, max_viernes, max_sabado, max_domingo) '
        'VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)',
        (nombre, color, *max_por_dia)
    )
    conn.commit()
    tag_id = cur.lastrowid
    conn.close()
    return tag_id


def asignar_tags_a_registro(registro_id: int, tag_ids):
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute('DELETE FROM registro_tags WHERE registro_id = ?', (registro_id,))
    for tid in tag_ids:
        cur.execute('INSERT OR IGNORE INTO registro_tags (registro_id, tag_id) VALUES (?, ?)',
                    (registro_id, tid))
    conn.commit()
    conn.close()


def obtener_tags_de_registro(registro_id: int):
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute('''SELECT t.* FROM tags t JOIN registro_tags rt ON t.id = rt.tag_id
                   WHERE rt.registro_id = ?''', (registro_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def crear_tags_iniciales():
    iniciales = ['Trabajo', 'Estudio', 'Proyecto personal']
    for nombre in iniciales:
        try:
            crear_tag(nombre)
        except sqlite3.IntegrityError:
            pass


def asignar_trabajo_a_todos():
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute('SELECT id FROM tags WHERE nombre = ?', ('Trabajo',))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    tag_id = row['id']
    cur.execute('SELECT id FROM registros')
    ids = [r['id'] for r in cur.fetchall()]
    for rid in ids:
        cur.execute('INSERT OR IGNORE INTO registro_tags (registro_id, tag_id) VALUES (?, ?)', (rid, tag_id))
    conn.commit()
    conn.close()


def obtener_registro_activo():
    """Retorna el registro de cronómetro actualmente en curso, si existe.

    Se considera activo únicamente un registro cuyo campo `manual` sea 0 y que no
    tenga hora de fin (`fin` es NULL). De esta manera, las entradas
    manuales (que no poseen hora de inicio ni de fin) no se interpretan
    erróneamente como un cronómetro en curso.
    """
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute('SELECT * FROM registros WHERE fin IS NULL AND manual = 0 ORDER BY id DESC LIMIT 1')
    registro = cur.fetchone()
    conn.close()
    return registro


def formatear_segundos(seg: int) -> str:
    """Convierte segundos en una cadena HH:MM (ignora los segundos)."""
    horas = seg // 3600
    minutos = (seg % 3600) // 60
    return f"{horas:02d}:{minutos:02d}"


def formatear_segundos_completo(seg: int) -> str:
    """Convierte segundos en una cadena HH:MM:SS."""
    horas = seg // 3600
    minutos = (seg % 3600) // 60
    segundos = seg % 60
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


class TimeTrackerHandler(BaseHTTPRequestHandler):
    """Manejador HTTP para nuestra aplicación de seguimiento de horas."""

    def do_GET(self):
        inicializar_db()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        # Mensajes opcionales por query string
        message = query.get('message', [None])[0]
        msg_type = query.get('type', [''])[0]

        if path == '/':
            self.render_index(message, msg_type)
        elif path.startswith('/logs'):
            self.render_logs(query, message, msg_type)
        elif path.startswith('/settings'):
            self.render_settings(message, msg_type)
        elif path.startswith('/calendar'):
            self.render_calendar(query, message, msg_type)
        elif path.startswith('/tags/delete/'):
            self.handle_delete_tag(path)
        elif path.startswith('/tags/color/'):
            self.handle_regen_color(path)
        elif path.startswith('/tags'):
            self.render_tags(message, msg_type)
        elif path.startswith('/delete/'):
            self.handle_delete(path)
        elif path.startswith('/static/'):
            self.serve_static(path)
        else:
            self.send_error(404, "Página no encontrada")

    def do_POST(self):
        inicializar_db()
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        data = parse_qs(body)
        # Extrae un valor del formulario, manejando listas
        def get_val(clave, default=''):
            return data.get(clave, [default])[0]

        if path == '/':
            accion = get_val('accion')
            descripcion = get_val('descripcion').strip() or None
            mensaje = ''
            tipo = 'success'
            if accion == 'start':
                tags_ids = [int(t) for t in data.get('tags', []) if t]
                if not tags_ids:
                    self.redirect_with_message('/', 'Debes indicar al menos un tag.', 'warning')
                    return
                reg_activo = obtener_registro_activo()
                if reg_activo:
                    mensaje = 'Ya hay un cronómetro en curso. Deténlo antes de iniciar uno nuevo.'
                    tipo = 'warning'
                else:
                    ahora = datetime.now()
                    conn = obtener_conexion()
                    cur = conn.cursor()
                    cur.execute(
                        'INSERT INTO registros (fecha, inicio, fin, duracion, descripcion, manual) VALUES (?, ?, ?, ?, ?, ?)',
                        (ahora.date().isoformat(), ahora.isoformat(), None, 0, descripcion, 0)
                    )
                    registro_id = cur.lastrowid
                    conn.commit()
                    conn.close()
                    asignar_tags_a_registro(registro_id, tags_ids)
                    mensaje = 'Cronómetro iniciado.'
            elif accion == 'stop':
                reg_activo = obtener_registro_activo()
                if not reg_activo:
                    mensaje = 'No hay un cronómetro en curso.'
                    tipo = 'warning'
                else:
                    ahora = datetime.now()
                    inicio = datetime.fromisoformat(reg_activo['inicio'])
                    duracion = int((ahora - inicio).total_seconds())
                    conn = obtener_conexion()
                    conn.execute(
                        'UPDATE registros SET fin = ?, duracion = ? WHERE id = ?',
                        (ahora.isoformat(), duracion, reg_activo['id'])
                    )
                    conn.commit()
                    conn.close()
                    mensaje = 'Cronómetro detenido.'
            elif accion == 'manual':
                # Registro manual con hora de inicio y fin (o duración)
                inicio_str = get_val('inicio_manual')
                fin_str = get_val('fin_manual')
                horas_d = get_val('duracion_horas', '0')
                minutos_d = get_val('duracion_minutos', '0')
                tags_ids = [int(t) for t in data.get('tags', []) if t]
                if not tags_ids:
                    self.redirect_with_message('/', 'Debes indicar al menos un tag.', 'warning')
                    return
                if not inicio_str:
                    mensaje = 'Debes indicar fecha y hora de inicio para el registro manual.'
                    tipo = 'warning'
                else:
                    inicio_dt = None
                    fin_dt = None
                    try:
                        inicio_dt = datetime.fromisoformat(inicio_str)
                    except ValueError:
                        inicio_dt = None
                    if not inicio_dt:
                        mensaje = 'Formato de fecha y hora de inicio no válido.'
                        tipo = 'warning'
                    else:
                        # Determina duración y fin
                        duracion = 0
                        if fin_str:
                            try:
                                fin_dt = datetime.fromisoformat(fin_str)
                            except ValueError:
                                fin_dt = None
                            if fin_dt and fin_dt > inicio_dt:
                                duracion = int((fin_dt - inicio_dt).total_seconds())
                            else:
                                mensaje = 'La fecha y hora de fin debe ser posterior al inicio.'
                                tipo = 'warning'
                        if duracion == 0:
                            # Intenta calcular duración a partir de campos de duración
                            try:
                                horas_int = int(horas_d or '0')
                                minutos_int = int(minutos_d or '0')
                            except ValueError:
                                horas_int = 0; minutos_int = 0
                            duracion = horas_int * 3600 + minutos_int * 60
                            if duracion > 0:
                                fin_dt = inicio_dt + timedelta(seconds=duracion)
                        if duracion <= 0:
                            mensaje = 'Debes indicar una duración o una fecha y hora de fin válidas.'
                            tipo = 'warning'
                        else:
                            # Guarda el registro manual con inicio y fin calculados
                            conn = obtener_conexion()
                            cur = conn.cursor()
                            cur.execute(
                                'INSERT INTO registros (fecha, inicio, fin, duracion, descripcion, manual) VALUES (?, ?, ?, ?, ?, ?)',
                                (inicio_dt.date().isoformat(), inicio_dt.isoformat(), fin_dt.isoformat(), duracion, descripcion, 1)
                            )
                            registro_id = cur.lastrowid
                            conn.commit()
                            conn.close()
                            asignar_tags_a_registro(registro_id, tags_ids)
                            mensaje = 'Entrada registrada.'
            elif accion == 'cancelar':
                # Cancelar horas (resta tiempo del saldo)
                fecha_cancelar = get_val('fecha_cancelar')
                horas_c = int(get_val('horas_cancelar', '0'))
                minutos_c = int(get_val('minutos_cancelar', '0'))
                tags_ids = [int(t) for t in data.get('tags', []) if t]
                if not tags_ids:
                    self.redirect_with_message('/', 'Debes indicar al menos un tag.', 'warning')
                    return
                if not fecha_cancelar:
                    mensaje = 'Debes indicar una fecha para cancelar horas.'
                    tipo = 'warning'
                else:
                    dur = horas_c * 3600 + minutos_c * 60
                    if dur == 0:
                        mensaje = 'La duración debe ser mayor a cero para cancelar.'
                        tipo = 'warning'
                    else:
                        dur = -dur
                        descripcion = descripcion or 'Cancelación de horas'
                        conn = obtener_conexion()
                        cur = conn.cursor()
                        cur.execute(
                            'INSERT INTO registros (fecha, inicio, fin, duracion, descripcion, manual) VALUES (?, ?, ?, ?, ?, ?)',
                            (fecha_cancelar, None, None, dur, descripcion, 1)
                        )
                        registro_id = cur.lastrowid
                        conn.commit()
                        conn.close()
                        asignar_tags_a_registro(registro_id, tags_ids)
                        mensaje = 'Cancelación registrada.'
            # Redirige a la página de inicio con mensaje
            self.redirect_with_message('/', mensaje, tipo)
        elif path == '/settings':
            accion = get_val('accion')
            if accion == 'init_tags':
                crear_tags_iniciales()
                self.redirect_with_message('/settings', 'Tags iniciales creados.', 'success')
            elif accion == 'assign_trabajo':
                asignar_trabajo_a_todos()
                self.redirect_with_message('/settings', 'Tag asignado a todos los registros.', 'success')
            else:
                horas = int(get_val('horas', '0'))
                minutos = int(get_val('minutos', '0'))
                total_minutos = horas * 60 + minutos
                if total_minutos <= 0:
                    self.redirect_with_message('/settings', 'La cantidad máxima diaria debe ser mayor a cero.', 'warning')
                else:
                    actualizar_horas_maximas(total_minutos)
                    self.redirect_with_message('/settings', 'Configuración actualizada.', 'success')
        elif path == '/tags':
            accion = get_val('accion')
            if accion == 'crear':
                nombre = get_val('nombre').strip()
                maximos = [int(get_val(d, '0') or '0') for d in DIAS_SEMANA]
                if not nombre:
                    self.redirect_with_message('/tags', 'Debes indicar un nombre.', 'warning')
                else:
                    try:
                        crear_tag(nombre, maximos)
                        self.redirect_with_message('/tags', 'Tag creado.', 'success')
                    except sqlite3.IntegrityError:
                        self.redirect_with_message('/tags', 'El tag ya existe.', 'warning')
            elif accion == 'editar':
                tag_id = int(get_val('id', '0'))
                nombre = get_val('nombre').strip()
                maximos = [int(get_val(d, '0') or '0') for d in DIAS_SEMANA]
                conn = obtener_conexion()
                try:
                    conn.execute(
                        'UPDATE tags SET nombre=?, max_diario=0, max_lunes=?, max_martes=?, max_miercoles=?, max_jueves=?, max_viernes=?, max_sabado=?, max_domingo=? WHERE id=?',
                        (nombre, *maximos, tag_id)
                    )
                    conn.commit()
                    self.redirect_with_message('/tags', 'Tag actualizado.', 'success')
                except sqlite3.IntegrityError:
                    self.redirect_with_message('/tags', 'Nombre de tag ya utilizado.', 'warning')
                finally:
                    conn.close()
            else:
                self.send_error(400, 'Acción de tag no válida')
        else:
            self.send_error(404, "Ruta no válida para POST")

    # Métodos de ayuda para procesamiento de rutas
    def redirect_with_message(self, location: str, message: str, msg_type: str):
        """Envía una redirección a una ruta con un mensaje en la query string."""
        if message:
            location = f"{location}?message={quote_plus(message)}&type={quote_plus(msg_type)}"
        self.send_response(303)
        self.send_header('Location', location)
        self.end_headers()

    def serve_static(self, path: str):
        """Sirve archivos estáticos como CSS o imágenes desde la carpeta static."""
        # Elimina el prefijo '/static/'
        rel_path = path[len('/static/') :]
        file_path = os.path.join(STATIC_DIR, rel_path)
        if not os.path.isfile(file_path):
            self.send_error(404, "Archivo estático no encontrado")
            return
        # Determina el tipo de contenido
        if file_path.endswith('.css'):
            content_type = 'text/css'
        elif file_path.endswith('.js'):
            content_type = 'application/javascript'
        elif file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
            # Soporta imágenes básicas
            ext = file_path.split('.')[-1].lower()
            content_type = f'image/{"jpeg" if ext == "jpg" else ext}'
        else:
            content_type = 'application/octet-stream'
        try:
            with open(file_path, 'rb') as f:
                contenido = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(contenido)))
            self.end_headers()
            self.wfile.write(contenido)
        except IOError:
            self.send_error(404, "No se pudo leer el archivo estático")

    def handle_delete(self, path: str):
        """Elimina un registro por su ID y redirige a los logs."""
        try:
            registro_id = int(path.split('/')[-1])
        except ValueError:
            self.send_error(400, "ID de registro no válido")
            return
        conn = obtener_conexion()
        conn.execute('DELETE FROM registros WHERE id = ?', (registro_id,))
        conn.commit()
        conn.close()
        self.redirect_with_message('/logs', 'Registro eliminado.', 'success')

    def handle_delete_tag(self, path: str):
        """Elimina un tag si no está asociado a registros."""
        try:
            tag_id = int(path.split('/')[-1])
        except ValueError:
            self.send_error(400, 'ID de tag no válido')
            return
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) as cnt FROM registro_tags WHERE tag_id = ?', (tag_id,))
        cnt = cur.fetchone()['cnt']
        if cnt > 0:
            conn.close()
            self.redirect_with_message('/tags', 'Este tag ya se ha utilizado por lo que no se puede eliminar.', 'warning')
            return
        cur.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        conn.commit()
        conn.close()
        self.redirect_with_message('/tags', 'Tag eliminado.', 'success')

    def handle_regen_color(self, path: str):
        """Regenera el color de un tag."""
        try:
            tag_id = int(path.split('/')[-1])
        except ValueError:
            self.send_error(400, 'ID de tag no válido')
            return
        conn = obtener_conexion()
        color = color_aleatorio()
        conn.execute('UPDATE tags SET color=? WHERE id=?', (color, tag_id))
        conn.commit()
        conn.close()
        self.redirect_with_message('/tags', 'Color regenerado.', 'success')

    def render_tags(self, message: str, msg_type: str):
        tags = obtener_tags()
        contenido = []
        contenido.append('<h1>Tags</h1>')
        contenido.append('<div class="card">')
        contenido.append('<h2>Crear nuevo tag</h2>')
        contenido.append('<form method="post" action="/tags">')
        contenido.append('<input type="hidden" name="accion" value="crear">')
        contenido.append('<label>Nombre:</label>')
        contenido.append('<input type="text" name="nombre" required>')
        for d in DIAS_SEMANA:
            contenido.append(f'<label>{d.capitalize()} (minutos):</label>')
            contenido.append(f'<input type="number" name="{d}" min="0" value="0">')
        contenido.append('<button type="submit" class="btn save">Crear</button>')
        contenido.append('</form>')
        contenido.append('</div>')
        if tags:
            contenido.append('<div class="card">')
            contenido.append('<h2>Tags existentes</h2>')
            contenido.append('<ul class="detalle-list">')
            for t in tags:
                contenido.append('<li class="detalle-item">')
                contenido.append(f'<span class="tag" style="background:{t["color"]};">{t["nombre"]}</span> ')
                contenido.append('<form method="post" action="/tags" class="acciones-manuales" style="margin-left:0.5rem;">')
                contenido.append('<input type="hidden" name="accion" value="editar">')
                contenido.append(f'<input type="hidden" name="id" value="{t["id"]}">')
                contenido.append(f'<input type="text" name="nombre" value="{t["nombre"]}" required>')
                for d in DIAS_SEMANA:
                    contenido.append(f'{d[:3].capitalize()}:<input type="number" name="{d}" min="0" value="{t["max_"+d]}" style="width:60px;">')
                contenido.append('<button type="submit" class="btn save">Guardar</button>')
                contenido.append('</form>')
                contenido.append(f'<a href="/tags/color/{t["id"]}" class="btn save">Color</a>')
                contenido.append(f'<a href="/tags/delete/{t["id"]}" class="btn delete">Eliminar</a>')
                contenido.append('</li>')
            contenido.append('</ul>')
            contenido.append('</div>')
        html = self.render_base('Tags - Registro de Horas', ''.join(contenido), '', message, msg_type)
        self.respond(html)

    # Renderizado de páginas
    def render_index(self, message: str, msg_type: str):
        """Genera la página principal con el cronómetro y formulario manual."""
        reg_activo = obtener_registro_activo()
        en_curso = False
        tiempo_transcurrido = 0
        if reg_activo:
            en_curso = True
            inicio = datetime.fromisoformat(reg_activo['inicio'])
            tiempo_transcurrido = int((datetime.now() - inicio).total_seconds())
        fecha_hoy = date.today()
        hoy_str = fecha_hoy.isoformat()
        dia_col = 'max_' + DIAS_SEMANA[fecha_hoy.weekday()]
        conn = obtener_conexion()
        cur = conn.cursor()
        # Totales por tag para hoy
        cur.execute(
            f'''SELECT t.*, SUM(r.duracion) as total FROM registros r
                JOIN registro_tags rt ON r.id = rt.registro_id
                JOIN tags t ON t.id = rt.tag_id
                WHERE r.fecha = ?
                GROUP BY t.id''',
            (hoy_str,)
        )
        tags_tot = cur.fetchall()
        # Registros sin tag
        cur.execute('''SELECT SUM(duracion) as total FROM registros WHERE fecha=? AND id NOT IN (SELECT registro_id FROM registro_tags)''', (hoy_str,))
        row = cur.fetchone()
        sin_tag_total = row['total'] or 0
        conn.close()
        # Agregar tiempo transcurrido del cronómetro activo
        por_tag = {t['id']: {'row': t, 'total': t['total']} for t in tags_tot}
        if reg_activo:
            tags_activos = obtener_tags_de_registro(reg_activo['id'])
            activos_ids = [t['id'] for t in tags_activos]
            for t in tags_activos:
                if t['id'] in por_tag:
                    por_tag[t['id']]['total'] += tiempo_transcurrido
                else:
                    t_dict = dict(t)
                    por_tag[t['id']] = {'row': t_dict, 'total': tiempo_transcurrido}
        else:
            activos_ids = []
        total_hoy_segundos = sin_tag_total + sum(v['total'] for v in por_tag.values())
        # Construye contenido HTML de la página
        contenido = []
        contenido.append('<h1>Registro de Horas</h1>')
        tags = obtener_tags()
        def selector_tags():
            if not tags:
                return '<p>No hay tags disponibles. Crea alguno en la sección Tags.</p>'
            html = ['<div class="tag-selector">']
            for t in tags:
                html.append(f'<label><input type="checkbox" name="tags" value="{t["id"]}"><span class="tag" style="background:{t["color"]};">{t["nombre"]}</span></label>')
            html.append('</div>')
            return ''.join(html)
        # Resumen de hoy por tag
        contenido.append('<div class="resumen-hoy card">')
        totales_js = {}
        for tid, info in por_tag.items():
            trow = info['row']
            total = info['total']
            max_seg = trow[dia_col] * 60
            diff = total - max_seg
            h = total // 3600
            m = (total % 3600) // 60
            abs_d = abs(diff)
            hd = abs_d // 3600
            md = (abs_d % 3600) // 60
            signo = '-' if diff < 0 else '+'
            clase = 'negativo' if diff < 0 else 'positivo'
            contenido.append(f"{trow['nombre']} : <span id='tag_total_{tid}'>{h:02d}:{m:02d}</span> (<span id='tag_diff_{tid}' class='diferencia {clase}'>{signo}{hd:02d}:{md:02d}</span>)<br>")
            totales_js[str(tid)] = {'total': total, 'max': max_seg}
        if sin_tag_total:
            h = sin_tag_total // 3600
            m = (sin_tag_total % 3600) // 60
            contenido.append(f'sin tag : {h:02d}:{m:02d}<br>')
        htot = total_hoy_segundos // 3600
        mtot = (total_hoy_segundos % 3600) // 60
        contenido.append(f"<strong>TOTAL : <span id='total_hoy'>{htot:02d}:{mtot:02d}</span></strong>")
        contenido.append('</div>')
        # Sección cronómetro
        contenido.append('<section class="cronometro card">')
        contenido.append('<h2>Cronómetro en tiempo real</h2>')
        contenido.append('<form method="post" action="/">')
        if en_curso:
            contenido.append(f'<p>Tiempo transcurrido: <span id="tiempo_transcurrido">{formatear_segundos_completo(tiempo_transcurrido)}</span></p>')
            contenido.append('<input type="hidden" name="accion" value="stop">')
            contenido.append('<button type="submit" class="btn stop">Detener</button>')
            extra_scripts = f"<script>\nlet segundosTranscurridos = {tiempo_transcurrido};\nlet totalHoySegundos = {total_hoy_segundos};\nfunction actualizarCronometro() {{\n  segundosTranscurridos++;\n  totalHoySegundos++;\n  const h = Math.floor(segundosTranscurridos/3600);\n  const m = Math.floor((segundosTranscurridos%3600)/60);\n  const s = segundosTranscurridos%60;\n  document.getElementById('tiempo_transcurrido').textContent = String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');\n  const ht = Math.floor(totalHoySegundos/3600);\n  const mt = Math.floor((totalHoySegundos%3600)/60);\n  document.getElementById('total_hoy').textContent = String(ht).padStart(2,'0')+':'+String(mt).padStart(2,'0');\n}}\nsetInterval(actualizarCronometro, 1000);\n</script>"
        else:
            contenido.append('<p>No hay un cronómetro corriendo actualmente.</p>')
            contenido.append('<input type="hidden" name="accion" value="start">')
            contenido.append('<label for="descripcion">Descripción (opcional):</label>')
            contenido.append('<input type="text" id="descripcion" name="descripcion" placeholder="¿Qué estás haciendo?">')
            contenido.append(selector_tags())
            contenido.append('<button type="submit" class="btn start">Iniciar</button>')
            extra_scripts = f"<script>let totalHoySegundos = {total_hoy_segundos};</script>"
        contenido.append('</form>')
        contenido.append('</section>')
        # Sección de registro manual con inicio y fin
        contenido.append('<section class="manual card">')
        contenido.append('<h2>Registrar horas manualmente</h2>')
        contenido.append('<form method="post" action="/">')
        contenido.append('<input type="hidden" name="accion" value="manual">')
        contenido.append('<label for="inicio_manual">Fecha y hora de inicio:</label>')
        contenido.append('<input type="datetime-local" id="inicio_manual" name="inicio_manual" required>')
        contenido.append('<div class="duracion-y-fin">')
        contenido.append('<div class="duracion-grupo">')
        contenido.append('<label for="duracion_horas">Duración (horas y minutos):</label>')
        contenido.append('<input type="number" id="duracion_horas" name="duracion_horas" min="0" value="0">')
        contenido.append('<input type="number" id="duracion_minutos" name="duracion_minutos" min="0" max="59" value="0">')
        contenido.append('</div>')
        contenido.append('<div class="fin-grupo">')
        contenido.append('<label for="fin_manual">Fecha y hora de fin:</label>')
        contenido.append('<input type="datetime-local" id="fin_manual" name="fin_manual">')
        contenido.append('</div>')
        contenido.append('</div>')
        contenido.append('<label for="descripcion_manual">Descripción (opcional):</label>')
        contenido.append('<input type="text" id="descripcion_manual" name="descripcion" placeholder="Descripción de la actividad">')
        contenido.append(selector_tags())
        contenido.append('<button type="submit" class="btn manual">Registrar manual</button>')
        contenido.append('</form>')
        # Sección cancelación de horas
        contenido.append('<h2>Cancelar horas</h2>')
        contenido.append('<form method="post" action="/">')
        contenido.append('<input type="hidden" name="accion" value="cancelar">')
        contenido.append('<label for="fecha_cancelar">Fecha:</label>')
        contenido.append('<input type="date" id="fecha_cancelar" name="fecha_cancelar" required>')
        contenido.append('<label for="horas_cancelar">Horas:</label>')
        contenido.append('<input type="number" id="horas_cancelar" name="horas_cancelar" min="0" value="0" required>')
        contenido.append('<label for="minutos_cancelar">Minutos:</label>')
        contenido.append('<input type="number" id="minutos_cancelar" name="minutos_cancelar" min="0" max="59" value="0" required>')
        contenido.append('<label for="descripcion_cancelar">Descripción (opcional):</label>')
        contenido.append('<input type="text" id="descripcion_cancelar" name="descripcion" placeholder="Descripción de cancelación">')
        contenido.append(selector_tags())
        contenido.append('<button type="submit" class="btn cancel">Cancelar horas</button>')
        contenido.append('</form>')
        contenido.append('</section>')
        # Script para sincronizar campos de duración y fin en el formulario manual
        extra_scripts += """
<script>
function pad(num) {
  return String(num).padStart(2,'0');
}
function updateFin() {
  const inicio = document.getElementById('inicio_manual').value;
  const horas = parseInt(document.getElementById('duracion_horas').value || '0');
  const minutos = parseInt(document.getElementById('duracion_minutos').value || '0');
  if (!inicio || (horas === 0 && minutos === 0)) {
    return;
  }
  const startDate = new Date(inicio);
  const endDate = new Date(startDate.getTime() + horas*3600*1000 + minutos*60*1000);
  const yyyy = endDate.getFullYear();
  const mm = pad(endDate.getMonth()+1);
  const dd = pad(endDate.getDate());
  const HH = pad(endDate.getHours());
  const MM = pad(endDate.getMinutes());
  document.getElementById('fin_manual').value = `${yyyy}-${mm}-${dd}T${HH}:${MM}`;
}
function updateDuracion() {
  const inicio = document.getElementById('inicio_manual').value;
  const fin = document.getElementById('fin_manual').value;
  if (!inicio || !fin) {
    return;
  }
  const startDate = new Date(inicio);
  const endDate = new Date(fin);
  let diffMs = endDate - startDate;
  if (diffMs < 0) diffMs = 0;
  const horas = Math.floor(diffMs / (3600*1000));
  const minutos = Math.floor((diffMs % (3600*1000)) / (60*1000));
  document.getElementById('duracion_horas').value = horas;
  document.getElementById('duracion_minutos').value = minutos;
}
document.getElementById('duracion_horas').addEventListener('input', updateFin);
document.getElementById('duracion_minutos').addEventListener('input', updateFin);
document.getElementById('inicio_manual').addEventListener('change', function() {
  updateFin();
  updateDuracion();
});
document.getElementById('fin_manual').addEventListener('change', updateDuracion);
</script>
"""
        html = self.render_base('Inicio - Registro de Horas', ''.join(contenido), extra_scripts, message, msg_type)
        self.respond(html)

    def render_logs(self, query, message, msg_type):
        """Genera la página de registros agrupados por día."""
        # Determina mes y año
        hoy = date.today()
        month = int(query.get('month', [hoy.month])[0])
        year = int(query.get('year', [hoy.year])[0])
        # Calcula rango de fechas
        desde = date(year, month, 1)
        if month == 12:
            hasta = date(year + 1, 1, 1)
        else:
            hasta = date(year, month + 1, 1)
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute('SELECT * FROM registros WHERE fecha >= ? AND fecha < ? ORDER BY fecha, id',
                    (desde.isoformat(), hasta.isoformat()))
        rows = cur.fetchall()
        # Agrupa por fecha
        registros_por_dia = {}
        for row in rows:
            registros_por_dia.setdefault(row['fecha'], []).append(row)
        tags_all = obtener_tags()
        acumulado_por_tag = {t['id']: {'nombre': t['nombre'], 'diferencia': 0} for t in tags_all}
        # Resta máximos por cada día del mes
        dia_iter = desde
        while dia_iter < hasta:
            col = 'max_' + DIAS_SEMANA[dia_iter.weekday()]
            for t in tags_all:
                acumulado_por_tag[t['id']]['diferencia'] -= t[col] * 60
            dia_iter += timedelta(days=1)
        resumen = []
        for f, regs in registros_por_dia.items():
            fecha_dt = date.fromisoformat(f)
            col = 'max_' + DIAS_SEMANA[fecha_dt.weekday()]
            total = sum(r['duracion'] for r in regs)
            cur.execute(f'''SELECT t.*, SUM(r.duracion) as total
                             FROM registros r JOIN registro_tags rt ON r.id = rt.registro_id
                             JOIN tags t ON t.id = rt.tag_id
                             WHERE r.fecha = ?
                             GROUP BY t.id''', (f,))
            tags_tot = [dict(r) for r in cur.fetchall()]
            cur.execute('''SELECT SUM(duracion) as total FROM registros WHERE fecha=? AND id NOT IN (SELECT registro_id FROM registro_tags)''', (f,))
            row = cur.fetchone()
            sin_tag_total = row['total'] or 0
            if sin_tag_total:
                tags_tot.append({'id': None, 'nombre': 'sin tag', 'color': '#666', col: 0, 'total': sin_tag_total})
                acumulado_por_tag.setdefault(None, {'nombre': 'sin tag', 'diferencia': 0})
                acumulado_por_tag[None]['diferencia'] += sin_tag_total
            diferencia = 0
            for t in tags_tot:
                max_seg = t[col] * 60 if t.get(col) is not None else 0
                diff_t = t['total'] - max_seg
                diferencia += diff_t
                if t.get('id') is not None:
                    acumulado_por_tag[t['id']]['diferencia'] += t['total']
            resumen.append({'fecha': f, 'total': total, 'diferencia': diferencia, 'registros': regs, 'tags': tags_tot, 'col': col})
        resumen.sort(key=lambda x: x['fecha'])
        conn.close()
        # Construye tabla HTML
        contenido = []
        contenido.append('<h1>Registros del mes</h1>')
        # Navegación entre meses
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        contenido.append('<div class="mes-navegacion">')
        contenido.append(f'<a href="/logs?month={prev_month}&year={prev_year}" class="mes-link">&lt; Mes anterior</a>')
        contenido.append(f'<span class="mes-actual">{month:02d}/{year}</span>')
        contenido.append(f'<a href="/logs?month={next_month}&year={next_year}" class="mes-link">Mes siguiente &gt;</a>')
        contenido.append('</div>')
        if resumen:
            contenido.append('<div class="card">')
            contenido.append('<table class="tabla-registros">')
            contenido.append('<thead><tr><th>Día</th><th>Total trabajado</th><th>Diferencia</th><th>Detalles</th></tr></thead>')
            contenido.append('<tbody>')
            for item in resumen:
                total_sec = item['total']
                horas_total = total_sec // 3600
                minutos_total = (total_sec % 3600) // 60
                diff_sec = item['diferencia']
                abs_sec = abs(diff_sec)
                horas_diff = abs_sec // 3600
                minutos_diff = (abs_sec % 3600) // 60
                signo = '-' if diff_sec < 0 else '+'
                clase = 'negativo' if diff_sec < 0 else 'positivo'
                contenido.append('<tr>')
                contenido.append(f'<td>{item["fecha"]}</td>')
                contenido.append('<td>')
                for t in item['tags']:
                    h_t = t['total'] // 3600
                    m_t = (t['total'] % 3600) // 60
                    max_seg = t[item['col']] * 60 if t.get(item['col']) is not None else 0
                    diff_t = t['total'] - max_seg
                    abs_t = abs(diff_t)
                    hd = abs_t // 3600
                    md = (abs_t % 3600) // 60
                    signo_t = '-' if diff_t < 0 else '+'
                    clase_t = 'negativo' if diff_t < 0 else 'positivo'
                    contenido.append(f'{t["nombre"]} : {h_t:02d}:{m_t:02d} (<span class="diferencia {clase_t}">{signo_t}{hd:02d}:{md:02d}</span>)<br>')
                contenido.append(f'<strong>TOTAL : {horas_total:02d}:{minutos_total:02d}</strong>')
                contenido.append('</td>')
                contenido.append(f'<td class="diferencia {clase}">{signo}{horas_diff:02d}:{minutos_diff:02d}</td>')
                contenido.append('<td>')
                contenido.append('<details><summary>Mostrar</summary>')
                contenido.append('<ul class="detalle-list">')
                for reg in item['registros']:
                    dur = reg['duracion']
                    h = dur // 3600
                    m = (dur % 3600) // 60
                    if reg['inicio']:
                        inicio = reg['inicio'][:19].replace('T', ' ')
                        fin = reg['fin'][:19].replace('T',' ') if reg['fin'] else '(en curso)'
                        info = f'Inicio: {inicio} - Fin: {fin}'
                    else:
                        info = 'Manual'
                    descripcion = reg['descripcion'] or 'Sin descripción'
                    tags_reg = obtener_tags_de_registro(reg['id'])
                    tags_html = ''.join(f'<span class="tag" style="background:{tr["color"]};">{tr["nombre"]}</span>' for tr in tags_reg)
                    contenido.append('<li class="detalle-item">')
                    contenido.append(f'<span class="detalle-info">{info} — Duración: {h:02d}:{m:02d} — {descripcion}<br>{tags_html}</span>')
                    contenido.append(f'<a href="/delete/{reg["id"]}" class="btn delete" onclick="return confirm(\'¿Estás seguro de eliminar este registro?\');">Eliminar</a>')
                    contenido.append('</li>')
                contenido.append('</ul>')
                contenido.append('</details>')
                contenido.append('</td>')
                contenido.append('</tr>')
            contenido.append('</tbody></table>')
            # Cálculo acumulado
            contenido.append('<div class="acumulado">')
            contenido.append('<strong>Diferencia acumulada del mes:</strong><br>')
            for info in acumulado_por_tag.values():
                diff = info['diferencia']
                abs_sec = abs(diff)
                h = abs_sec // 3600
                m = (abs_sec % 3600) // 60
                signo = '-' if diff < 0 else '+'
                clase = 'negativo' if diff < 0 else 'positivo'
                contenido.append(f"{info['nombre']}: <span class='diferencia {clase}'>{signo}{h:02d}:{m:02d}</span><br>")
            contenido.append('</div>')
            contenido.append('</div>')  # fin card
        else:
            contenido.append('<p>No hay registros para este mes.</p>')
        html = self.render_base('Registros - Registro de Horas', ''.join(contenido), '', message, msg_type)
        self.respond(html)

    def render_settings(self, message: str, msg_type: str):
        """Genera la página de configuración de horas máximas."""
        minutos_maximos = obtener_horas_maximas()
        horas_actuales = minutos_maximos // 60
        minutos_actuales = minutos_maximos % 60
        contenido = []
        contenido.append('<h1>Configuración</h1>')
        contenido.append('<p>Define la cantidad máxima de horas laborales por día. Esta configuración se utiliza para calcular las diferencias de horas en los registros.</p>')
        contenido.append('<div class="card">')
        contenido.append('<form method="post" action="/settings" class="form-config">')
        contenido.append('<label for="horas">Horas:</label>')
        contenido.append(f'<input type="number" id="horas" name="horas" min="0" value="{horas_actuales}" required>')
        contenido.append('<label for="minutos">Minutos:</label>')
        contenido.append(f'<input type="number" id="minutos" name="minutos" min="0" max="59" value="{minutos_actuales}" required>')
        contenido.append('<button type="submit" class="btn save">Guardar</button>')
        contenido.append('</form>')
        contenido.append(f'<p>Valor actual: {horas_actuales}h {minutos_actuales}m por día.</p>')
        contenido.append('</div>')  # fin card
        contenido.append('<div class="card">')
        contenido.append('<h2>Acciones de tags</h2>')
        contenido.append('<form method="post" action="/settings" style="margin-bottom:0.5rem;">')
        contenido.append('<input type="hidden" name="accion" value="init_tags">')
        contenido.append('<button type="submit" class="btn save">Crear tags iniciales</button>')
        contenido.append('</form>')
        contenido.append('<form method="post" action="/settings">')
        contenido.append('<input type="hidden" name="accion" value="assign_trabajo">')
        contenido.append('<button type="submit" class="btn save">Asignar "Trabajo" a todos los registros</button>')
        contenido.append('</form>')
        contenido.append('</div>')
        html = self.render_base('Configuración - Registro de Horas', ''.join(contenido), '', message, msg_type)
        self.respond(html)

    def render_calendar(self, query, message, msg_type):
        """Genera una vista de calendario semanal de los registros."""
        # Determina la semana a mostrar
        hoy = date.today()
        week_str = query.get('week', [None])[0]
        if week_str:
            try:
                ref_date = datetime.fromisoformat(week_str).date()
            except ValueError:
                ref_date = hoy
        else:
            ref_date = hoy
        # Calcula el lunes de la semana
        start_of_week = ref_date - timedelta(days=ref_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        # Consulta registros de la semana
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute('SELECT * FROM registros WHERE fecha >= ? AND fecha <= ? ORDER BY fecha, inicio',
                    (start_of_week.isoformat(), end_of_week.isoformat()))
        rows = cur.fetchall()
        conn.close()
        # Agrupa eventos por día e incluye inicio/fin para manuales
        events = []  # lista de eventos para JS
        # Resumen por día
        minutos_maximos = obtener_horas_maximas()
        summaries = []
        # Prepara diccionario para sumar
        duracion_por_dia = {i: 0 for i in range(7)}
        for row in rows:
            # Determina hora de inicio y fin para cada registro
            if row['inicio']:
                try:
                    inicio_dt = datetime.fromisoformat(row['inicio'])
                except Exception:
                    inicio_dt = datetime.fromisoformat(row['fecha'] + 'T00:00:00')
            else:
                inicio_dt = datetime.fromisoformat(row['fecha'] + 'T00:00:00')
            if row['fin']:
                try:
                    fin_dt = datetime.fromisoformat(row['fin'])
                except Exception:
                    fin_dt = inicio_dt + timedelta(seconds=row['duracion'])
            else:
                fin_dt = inicio_dt + timedelta(seconds=row['duracion'])
            # Asegura que el evento caiga dentro de la semana (puede cruzar día)
            current_start = inicio_dt
            current_end = fin_dt
            # Si un evento se extiende a otro día, lo recortamos hasta medianoche del mismo día
            # y creamos múltiples eventos (simplificación)
            while current_start.date() <= current_end.date() and current_start.date() <= end_of_week:
                day_index = (current_start.date() - start_of_week).days
                if 0 <= day_index <= 6:
                    # Determina fin de este día (medianoche del día siguiente)
                    day_end_dt = datetime.combine(current_start.date() + timedelta(days=1), datetime.min.time())
                    event_end_dt = min(current_end, day_end_dt)
                    start_minutes = current_start.hour * 60 + current_start.minute + current_start.second / 60.0
                    duration_minutes = (event_end_dt - current_start).total_seconds() / 60.0
                    events.append({
                        'day': day_index,
                        'start': start_minutes,
                        'duration': duration_minutes,
                        'descripcion': row['descripcion'] or '',
                        'id': row['id']
                    })
                    # Suma duración para resumen
                    duracion_por_dia[day_index] += (event_end_dt - current_start).total_seconds()
                # Avanza al siguiente día
                current_start = datetime.combine(current_start.date() + timedelta(days=1), datetime.min.time())
                if current_start < fin_dt:
                    continue
                else:
                    break
        # Genera summaries
        for i in range(7):
            day_date = start_of_week + timedelta(days=i)
            total_sec = int(duracion_por_dia[i])
            diff_sec = total_sec - minutos_maximos * 60
            summaries.append({
                'date': day_date.isoformat(),
                'total': total_sec,
                'diferencia': diff_sec
            })
        # Prepara navegación de semanas
        prev_week = start_of_week - timedelta(days=7)
        next_week = start_of_week + timedelta(days=7)
        # Crea HTML de la página
        contenido = []
        contenido.append('<h1>Calendario semanal</h1>')
        contenido.append('<div class="calendar-controls">')
        contenido.append(f'<a href="/calendar?week={prev_week.isoformat()}" class="week-nav">&lt; Semana anterior</a>')
        contenido.append(f'<span class="week-range">{start_of_week.strftime("%d/%m/%Y")} - {end_of_week.strftime("%d/%m/%Y")}</span>')
        contenido.append(f'<a href="/calendar?week={next_week.isoformat()}" class="week-nav">Semana siguiente &gt;</a>')
        contenido.append('<div class="zoom-buttons">')
        contenido.append('<button type="button" data-zoom="60">1h</button>')
        contenido.append('<button type="button" data-zoom="30">30m</button>')
        contenido.append('<button type="button" data-zoom="15">15m</button>')
        contenido.append('</div>')
        contenido.append('</div>')
        # Contenedor del calendario en una tarjeta
        contenido.append('<div class="card">')
        contenido.append('<div class="calendar-grid" id="calendarGrid">')
        contenido.append('<div class="time-labels" id="timeLabels"></div>')
        # Nombres de los días en español
        nombres_dias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        for i in range(7):
            summary = summaries[i]
            total_sec = summary['total']
            horas = total_sec // 3600
            minutos = (total_sec % 3600) // 60
            diff_sec = summary['diferencia']
            abs_sec = abs(diff_sec)
            horas_dif = abs_sec // 3600
            minutos_dif = (abs_sec % 3600) // 60
            signo = '-' if diff_sec < 0 else '+'
            clase = 'negativo' if diff_sec < 0 else 'positivo'
            contenido.append(f'<div class="day-column" data-day-index="{i}">')
            contenido.append(f'<div class="day-header">{nombres_dias[i]} { (start_of_week + timedelta(days=i)).strftime("%d/%m") }<br><small>{horas:02d}:{minutos:02d} (<span class="diferencia {clase}">{signo}{horas_dif:02d}:{minutos_dif:02d}</span>)</small></div>')
            contenido.append('<div class="events-container"></div>')
            contenido.append('</div>')
        contenido.append('</div>')
        contenido.append('</div>')  # fin card
        # Prepara datos JSON para JS
        events_json = json.dumps(events)
        summaries_json = json.dumps(summaries)
        # Añade script para dibujar eventos y etiquetas de tiempo
        extra_scripts = f"""
<script>
const eventsData = {events_json};
let slotMinutes = 30; // valor por defecto
// Genera etiquetas de tiempo (solo horas)
function renderTimeLabels(pixelPerMinute) {{
  const container = document.getElementById('timeLabels');
  container.innerHTML = '';
  for (let h = 0; h < 24; h++) {{
    const label = document.createElement('div');
    label.className = 'time-label';
    label.textContent = (String(h).padStart(2,'0') + ':00');
    label.style.top = (h * 60 * pixelPerMinute) + 'px';
    container.appendChild(label);
  }}
}}
function renderEvents(pixelPerMinute) {{
  // Limpia contenedores
  document.querySelectorAll('.events-container').forEach(c => c.innerHTML = '');
  // Ajusta altura de contenedores
  const totalHeight = 1440 * pixelPerMinute;
  document.querySelectorAll('.events-container').forEach(c => {{ c.style.height = totalHeight + 'px'; }});
  document.getElementById('timeLabels').style.height = totalHeight + 'px';
  eventsData.forEach(ev => {{
    const col = document.querySelector(`.day-column[data-day-index="${{ev.day}}"] .events-container`);
    if (!col) return;
    const div = document.createElement('div');
    div.className = 'event-block';
    div.textContent = ev.descripcion || '';
    div.style.top = (ev.start * pixelPerMinute) + 'px';
    div.style.height = (ev.duration * pixelPerMinute) + 'px';
    col.appendChild(div);
  }});
}}
function updateZoom(minutes) {{
  slotMinutes = minutes;
  let pixelPerMinute;
  if (minutes == 60) {{ pixelPerMinute = 0.5; }}
  else if (minutes == 30) {{ pixelPerMinute = 1; }}
  else {{ pixelPerMinute = 2; }}
  renderTimeLabels(pixelPerMinute);
  renderEvents(pixelPerMinute);
}}
// Inicializar botones de zoom
document.querySelectorAll('.zoom-buttons button').forEach(btn => {{
  btn.addEventListener('click', function() {{
    const val = parseInt(this.getAttribute('data-zoom'));
    updateZoom(val);
  }});
}});
// Render inicial
updateZoom(slotMinutes);
</script>
"""
        html = self.render_base('Calendario semanal - Registro de Horas', ''.join(contenido), extra_scripts, message, msg_type)
        self.respond(html)

    def render_base(self, title: str, content_html: str, extra_scripts: str, message: str, msg_type: str) -> str:
        """Construye la plantilla base con navegación y mensajes."""
        # Mensajes flash
        flash_html = ''
        if message:
            clase = 'success' if msg_type == 'success' else 'warning'
            flash_html = f'<div class="flash-messages"><div class="flash {clase}">{message}</div></div>'
        return f"""
<!DOCTYPE html>
<html lang=\"es\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{title}</title>
    <link rel=\"stylesheet\" href=\"/static/style.css\">
    <script src=\"https://code.jquery.com/jquery-3.6.0.min.js\"></script>
</head>
<body>
    <nav class=\"navbar\">
        <ul>
            <li><a href=\"/\">Inicio</a></li>
            <li><a href=\"/logs\">Registros</a></li>
            <li><a href=\"/calendar\">Calendario</a></li>
            <li><a href=\"/settings\">Configuración</a></li>
            <li><a href=\"/tags\">Tags</a></li>
        </ul>
    </nav>
    <div class=\"container\">
        {flash_html}
        {content_html}
    </div>
    {extra_scripts}
</body>
</html>
"""

    def respond(self, html: str):
        """Envía una respuesta HTML al cliente."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


def run_server(port: int = 8000):
    """Inicia el servidor en el puerto especificado."""
    inicializar_db()
    server_address = ('', port)
    httpd = HTTPServer(server_address, TimeTrackerHandler)
    print(f"Servidor iniciado en http://localhost:{port}")
    httpd.serve_forever()


if __name__ == '__main__':
    run_server()