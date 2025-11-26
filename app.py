import os
import json
from datetime import datetime
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# =================== Configuración de la app ===================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_secreta_demo")  # Producción: usar variable de entorno

# Configuración de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Por favor inicia sesión para acceder a esta página."

# =================== Conexión a MySQL ===================

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.environ.get("DB_HOST", "database-1.c9kaeqiwud9r.us-east-1.rds.amazonaws.com"),
            database=os.environ.get("DB_NAME", "FormularioWeb"),
            user=os.environ.get("DB_USER", "admin"),
            password=os.environ.get("DB_PASS", "12345678"),
            port=int(os.environ.get("DB_PORT", 3306))
        )
        return conn
    except mysql.connector.Error as e:
        print(f"❌ Error de conexión a MySQL: {e}")
        return None

# =================== Creación de tablas ===================

def create_tables():
    conn = get_db_connection()
    if not conn:
        print("❌ No se pudo conectar a MySQL para crear tablas")
        return

    try:
        cursor = conn.cursor()
        
        # Usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(100) UNIQUE NOT NULL,
                telefono VARCHAR(20),
                password VARCHAR(200) NOT NULL,
                puntos INT DEFAULT 0,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                social_id VARCHAR(100) NULL,
                provider VARCHAR(50) NULL
            )
        ''')
        
        # Direcciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS direcciones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                alias VARCHAR(50),
                calle VARCHAR(200) NOT NULL,
                ciudad VARCHAR(100) NOT NULL,
                estado VARCHAR(100),
                codigo_postal VARCHAR(20),
                pais VARCHAR(100) NOT NULL,
                es_principal TINYINT(1) DEFAULT 0,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')
        
        # Pedidos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pedidos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NULL,
                nombre_cliente VARCHAR(100) NOT NULL,
                email_cliente VARCHAR(100) NOT NULL,
                telefono_cliente VARCHAR(20) NOT NULL,
                direccion_cliente TEXT NOT NULL,
                metodo_pago VARCHAR(50) NOT NULL,
                fecha_pedido DATETIME DEFAULT CURRENT_TIMESTAMP,
                total DECIMAL(10,2) NOT NULL,
                estado VARCHAR(50) DEFAULT 'pendiente',
                datos_pedido TEXT,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
            )
        ''')
        
        # Reseñas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resenas (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                producto_id INT NOT NULL,
                calificacion INT NOT NULL,
                comentario TEXT,
                fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')
        
        # Lista de deseos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lista_deseos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                producto_id INT NOT NULL,
                fecha_agregado DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')
        
        # Preferencias de notificación
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS preferencias_notificacion (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                email_notificaciones TINYINT(1) DEFAULT 1,
                sms_notificaciones TINYINT(1) DEFAULT 0,
                emails_promocionales TINYINT(1) DEFAULT 1,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')
        
        # Contactos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contactos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                mensaje TEXT NOT NULL,
                fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                ip_cliente VARCHAR(45) NULL
            )
        ''')

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Todas las tablas creadas o verificadas correctamente")
    except Exception as e:
        print(f"❌ Error creando tablas: {e}")

# Llamar a create_tables al iniciar la app
create_tables()

# =================== Usuario Flask-Login ===================

class User(UserMixin):
    def __init__(self, id, email, telefono, puntos):
        self.id = id
        self.email = email
        self.telefono = telefono
        self.puntos = puntos

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, email, telefono, puntos FROM usuarios WHERE id = %s", (user_id,))
        data = cursor.fetchone()
        return User(data["id"], data["email"], data["telefono"], data["puntos"]) if data else None
    except Exception as e:
        print(f"❌ Error cargando usuario: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

# =================== Helper: puntos ===================

def agregar_puntos(usuario_id, monto):
    """Agregar puntos por compras (1 punto cada S/10)"""
    puntos = int(float(monto) / 10)
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET puntos = puntos + %s WHERE id = %s", (puntos, usuario_id))
        conn.commit()
        return puntos
    except Exception as e:
        print(f"❌ Error agregando puntos: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()

# =================== Rutas de autenticación ===================

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        email = request.form.get("email")
        telefono = request.form.get("telefono")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not all([email, telefono, password, confirm_password]):
            flash("Completa todos los campos.", "error")
            return render_template("registro.html")

        if password != confirm_password:
            flash("Las contraseñas no coinciden.", "error")
            return render_template("registro.html")

        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.", "error")
            return render_template("registro.html")

        conn = get_db_connection()
        if not conn:
            flash("Error de conexión con la base de datos.", "error")
            return render_template("registro.html")

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("El correo ya está registrado.", "error")
                return render_template("registro.html")

            hashed_password = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO usuarios (email, telefono, password) VALUES (%s, %s, %s)",
                (email, telefono, hashed_password),
            )
            conn.commit()
            flash("¡Registro exitoso! Ahora puedes iniciar sesión.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            print(f"❌ Error en registro: {e}")
            flash("Error al registrar. Intenta nuevamente.", "error")
            return render_template("registro.html")
        finally:
            cursor.close()
            conn.close()
    return render_template("registro.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("email")
        contraseña = request.form.get("password")

        conn = get_db_connection()
        if not conn:
            flash("Error de conexión con la base de datos.", "error")
            return render_template("login.html")

        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (correo,))
            account = cursor.fetchone()
            if account and check_password_hash(account["password"], contraseña):
                user = User(account["id"], account["email"], account["telefono"], account["puntos"])
                login_user(user)
                flash("Inicio de sesión exitoso", "success")
                return redirect(url_for("perfil"))
            else:
                flash("Correo o contraseña incorrectos", "error")
        finally:
            cursor.close()
            conn.close()
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Has cerrado sesión correctamente", "info")
    return redirect(url_for("login"))

# ===== RUTAS DE PERFIL Y USUARIO (modificadas para MySQL) =====

@app.route("/perfil")
@login_required
def perfil():
    conn = get_db_connection()
    user_data = {}
    
    if conn:
        try:
            cursor = conn.cursor()
            
            # Obtener direcciones
            cursor.execute('SELECT * FROM direcciones WHERE usuario_id = %s', (current_user.id,))
            direcciones = []
            for row in cursor.fetchall():
                direcciones.append({
                    'id': row[0],
                    'alias': row[2],
                    'calle': row[3],
                    'ciudad': row[4],
                    'estado': row[5],
                    'codigo_postal': row[6],
                    'pais': row[7],
                    'es_principal': bool(row[8])
                })
            
            # Obtener pedidos
            cursor.execute('SELECT * FROM pedidos WHERE usuario_id = %s ORDER BY fecha_pedido DESC', (current_user.id,))
            pedidos = []
            for row in cursor.fetchall():
                pedidos.append({
                    'id': row[0],
                    'fecha_pedido': row[2],
                    'total': float(row[3]),
                    'estado': row[4],
                    'datos_pedido': row[5]
                })
            
            # Obtener lista de deseos
            cursor.execute('SELECT * FROM lista_deseos WHERE usuario_id = %s', (current_user.id,))
            lista_deseos = []
            for row in cursor.fetchall():
                lista_deseos.append({
                    'id': row[0],
                    'producto_id': row[2],
                    'fecha_agregado': row[3]
                })
            
            # Obtener preferencias
            cursor.execute('SELECT * FROM preferencias_notificacion WHERE usuario_id = %s', (current_user.id,))
            pref_data = cursor.fetchone()
            preferencias = {
                'email_notificaciones': bool(pref_data[2]) if pref_data else True,
                'sms_notificaciones': bool(pref_data[3]) if pref_data else False,
                'emails_promocionales': bool(pref_data[4]) if pref_data else True
            }
            
            cursor.close()
            conn.close()
            
            user_data = {
                'direcciones': direcciones,
                'pedidos': pedidos,
                'lista_deseos': lista_deseos,
                'preferencias': preferencias
            }
            
        except Exception as e:
            print(f"Error obteniendo datos del perfil: {e}")
    
    return render_template('perfil.html', user_data=user_data)

@app.route("/agregar_direccion", methods=['POST'])
@login_required
def agregar_direccion():
    alias = request.form.get('alias')
    calle = request.form.get('calle')
    ciudad = request.form.get('ciudad')
    estado = request.form.get('estado')
    codigo_postal = request.form.get('codigo_postal')
    pais = request.form.get('pais')
    es_principal = 1 if request.form.get('es_principal') else 0
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO direcciones (usuario_id, alias, calle, ciudad, estado, codigo_postal, pais, es_principal) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (current_user.id, alias, calle, ciudad, estado, codigo_postal, pais, es_principal)
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash('Dirección agregada exitosamente', 'success')
        except Exception as e:
            print(f"Error agregando dirección: {e}")
            flash('Error al agregar la dirección', 'error')
    
    return redirect(url_for('perfil'))

@app.route("/agregar_favorito/<int:producto_id>", methods=['POST'])
@login_required
def agregar_favorito(producto_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Verificar si ya está en la lista
            cursor.execute('SELECT id FROM lista_deseos WHERE usuario_id = %s AND producto_id = %s', 
                            (current_user.id, producto_id))
            if not cursor.fetchone():
                cursor.execute(
                    'INSERT INTO lista_deseos (usuario_id, producto_id) VALUES (%s, %s)',
                    (current_user.id, producto_id)
                )
                conn.commit()
                flash('Producto agregado a favoritos', 'success')
            else:
                flash('El producto ya está en tu lista de favoritos', 'info')
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error agregando a favoritos: {e}")
            flash('Error al agregar a favoritos', 'error')
    
    return redirect(request.referrer or url_for('productos'))

@app.route("/eliminar_favorito/<int:item_id>", methods=['POST'])
@login_required
def eliminar_favorito(item_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM lista_deseos WHERE id = %s AND usuario_id = %s', 
                            (item_id, current_user.id))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Producto eliminado de favoritos', 'success')
        except Exception as e:
            print(f"Error eliminando favorito: {e}")
            flash('Error al eliminar de favoritos', 'error')
    
    return redirect(url_for('perfil'))

@app.route("/actualizar_preferencias", methods=['POST'])
@login_required
def actualizar_preferencias():
    email_notificaciones = 1 if request.form.get('email_notificaciones') else 0
    sms_notificaciones = 1 if request.form.get('sms_notificaciones') else 0
    emails_promocionales = 1 if request.form.get('emails_promocionales') else 0
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''UPDATE preferencias_notificacion 
                SET email_notificaciones = %s, sms_notificaciones = %s, emails_promocionales = %s
                WHERE usuario_id = %s''',
                (email_notificaciones, sms_notificaciones, emails_promocionales, current_user.id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash('Preferencias actualizadas exitosamente', 'success')
        except Exception as e:
            print(f"Error actualizando preferencias: {e}")
            flash('Error al actualizar preferencias', 'error')
    
    return redirect(url_for('perfil'))

# ===== SISTEMA DE PEDIDOS Y FACTURAS (modificado para MySQL) =====

def agregar_puntos(usuario_id, monto):
    """Agregar puntos basados en el monto de compra (1 punto por cada S/ 10)"""
    puntos = int(monto / 10)
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('UPDATE usuarios SET puntos = puntos + %s WHERE id = %s', (puntos, usuario_id))
            conn.commit()
            cursor.close()
            conn.close()
            return puntos
        except Exception as e:
            print(f"Error agregando puntos: {e}")
    return 0

@app.route("/crear_pedido", methods=['POST'])
@login_required
def crear_pedido():
    datos_pedido = request.form.get('datos_pedido')
    total = request.form.get('total')
    
    try:
        datos_json = json.loads(datos_pedido)
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO pedidos (usuario_id, total, estado, datos_pedido) VALUES (%s, %s, %s, %s)',
                (current_user.id, total, 'completado', datos_pedido)
            )
            conn.commit()
            
            # Agregar puntos
            puntos_ganados = agregar_puntos(current_user.id, float(total))
            
            cursor.close()
            conn.close()
            
            flash(f'¡Pedido realizado exitosamente! Ganaste {puntos_ganados} puntos.', 'success')
            return redirect(url_for('perfil'))
    except Exception as e:
        print(f"Error creando pedido: {e}")
        flash('Error al crear el pedido', 'error')
    
    return redirect(request.referrer or url_for('productos'))

@app.route("/descargar_factura/<int:pedido_id>")
@login_required
def descargar_factura(pedido_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pedidos WHERE id = %s AND usuario_id = %s', (pedido_id, current_user.id))
            pedido_data = cursor.fetchone()
            
            if not pedido_data:
                flash('Pedido no encontrado', 'error')
                return redirect(url_for('perfil'))
            
            # Crear PDF
            buffer = BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)
            
            # Encabezado
            p.drawString(100, 750, "AGRÍCOLA GREEN CROP")
            p.drawString(100, 735, "Factura de Compra")
            p.drawString(100, 720, f"Factura #: {pedido_data[0]}")
            p.drawString(100, 705, f"Fecha: {pedido_data[2].strftime('%d/%m/%Y %H:%M')}")
            p.drawString(100, 690, f"Cliente: {current_user.email}")
            
            # Detalles del pedido
            p.drawString(100, 660, "Detalles del Pedido:")
            y = 645
            
            datos_pedido = json.loads(pedido_data[5])
            for item in datos_pedido.get('items', []):
                p.drawString(100, y, f"- {item['nombre']} x {item['cantidad']} - S/ {item['precio']}")
                y -= 15
            
            p.drawString(100, y-20, f"Total: S/ {pedido_data[3]}")
            p.drawString(100, y-40, f"Estado: {pedido_data[4]}")
            
            p.showPage()
            p.save()
            
            buffer.seek(0)
            cursor.close()
            conn.close()
            
            return send_file(buffer, as_attachment=True, download_name=f'factura_{pedido_id}.pdf', mimetype='application/pdf')
            
        except Exception as e:
            print(f"Error generando factura: {e}")
            flash('Error al generar la factura', 'error')
    
    return redirect(url_for('perfil'))

# ===== RUTAS EXISTENTES (sin cambios) =====

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")

@app.route("/chat", methods=['POST'])
def chat():
    user_message = request.json.get('message', '').lower()

    if user_message in ["hola", "menu", "inicio", "ayuda"]:
        return jsonify({
            "response": "👋 ¡Hola! Soy el chatbot de <b>Agrícola Green Crop</b> 🌱<br>"
                        "Estoy aquí para ayudarte con todo lo que necesites sobre nuestros productos y servicios.<br><br>"
                        "Ofrecemos <b>delivery rápido</b>, <b>asesoramiento personalizado</b> y todo lo que tu cultivo necesita "
                        "para crecer fuerte y sano. 🚜✨<br><br>💬 ¿En qué puedo ayudarte hoy?",
            "options": ["Fertilizantes", "Qué ofrecemos", "Precios", "Asesoramiento"]
        })
    elif "fertilizantes" in user_message:
        return jsonify({
            "response": "🌾 En <b>Agrícola Green Crop</b> contamos con una amplia variedad de <b>fertilizantes</b> "
                        "para que tus cultivos crezcan sanos y fuertes.<br><br>"
                        "Pueden ser <b>orgánicos</b> o <b>químicos</b>, según las necesidades de tu tierra. 🌱",
            "options": ["Orgánicos", "Químicos"]
        })
    elif "orgánicos" in user_message:
        return jsonify({
            "response": "🌿 Nuestros <b>fertilizantes orgánicos</b> son 100% naturales y ayudan a mejorar la calidad del suelo.<br><br>"
                        "Contamos con <b>compost</b>, <b>humus de lombriz</b> y <b>biofertilizantes líquidos</b> ideales para todo tipo de cultivo. ♻",
            "options": ["Ver precios", "Qué ofrecemos", "Asesoramiento"]
        })
    elif "químicos" in user_message:
        return jsonify({
            "response": "💧 Los <b>fertilizantes químicos</b> de <b>Agrícola Green Crop</b> brindan una nutrición rápida y efectiva a tus cultivos.<br><br>"
                        "Disponemos de <b>nitrato de amonio</b>, <b>urea</b> y <b>fosfato diamónico</b>, productos de alta pureza y rendimiento. ⚗",
            "options": ["Ver precios", "Qué ofrecemos", "Asesoramiento"]
        })
    elif "qué ofrecemos" in user_message or "ofrecemos" in user_message:
        return jsonify({
            "response": "📦 En <b>Agrícola Green Crop</b> te ofrecemos soluciones completas para el campo:<br><br>"
                        "✅ <b>Fertilizantes de alta calidad</b><br>"
                        "✅ <b>Asesoramiento técnico personalizado</b><br>"
                        "✅ <b>Delivery rápido</b> a todo el país<br>"
                        "✅ <b>Promociones especiales</b> por temporada 🌾<br><br>"
                        "Todo lo que tu cultivo necesita, en un solo lugar.",
            "options": ["Fertilizantes", "Precios", "Asesoramiento"]
        })
    elif "precio" in user_message or "precios" in user_message:
        return jsonify({
            "response": "💲 Nuestros precios varían según el tipo de producto y la cantidad que necesites.<br><br>"
                        "Cuéntame qué cultivo tienes y te ayudaremos a cotizar el fertilizante más adecuado. 🌽☕🥔",
            "options": ["Papa", "Maíz", "Café"]
        })
    elif "papa" in user_message:
        return jsonify({
            "response": "🥔 Para el cultivo de <b>papa</b>, recomendamos fertilizantes ricos en nitrógeno y potasio.<br><br>"
                        "💲 Precio aproximado: desde <b>S/ 45 por saco</b> (según tipo y presentación).",
            "options": ["Fertilizantes", "Asesoramiento"]
        })
    elif "maíz" in user_message:
        return jsonify({
            "response": "🌽 Para el <b>maíz</b>, sugerimos fertilizantes con fósforo y zinc para un mejor crecimiento y producción.<br><br>"
                        "💲 Precio aproximado: desde <b>S/ 50 por saco</b>.",
            "options": ["Fertilizantes", "Asesoramiento"]
        })
    elif "café" in user_message:
        return jsonify({
            "response": "☕ En el caso del <b>café</b>, usamos fertilizantes equilibrados que mejoran la floración y el grano.<br><br>"
                        "💲 Precio aproximado: desde <b>S/ 55 por saco</b>.",
            "options": ["Fertilizantes", "Asesoramiento"]
        })
    elif "asesoramiento" in user_message or "asesor" in user_message:
        return jsonify({
            "response": "📞 En <b>Agrícola Green Crop</b> contamos con expertos listos para asesorarte.<br><br>"
                        "Recibirás <b>recomendaciones personalizadas</b> según tu tipo de cultivo y el estado del suelo. 🌱<br><br>"
                        "Puedes contactarnos por:<br>📧 <b>info@agricolagreencrop.com</b><br>📱 <b>WhatsApp: +51 999 888 777</b>",
            "options": ["Fertilizantes", "Qué ofrecemos", "Precios"]
        })
    else:
        return jsonify({
            "response": "🤔 No entendí tu mensaje. Por favor elige una de estas opciones 👇",
            "options": ["Fertilizantes", "Qué ofrecemos", "Precios", "Asesoramiento"]
        })

@app.route("/productos")
def productos():
    return render_template("productos.html")

@app.route("/servicio")
def servicio():
    return render_template("servicio.html")

@app.route("/contact", methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        try:
            nombre = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            mensaje = request.form.get('message', '').strip()
            ip_cliente = request.remote_addr  
            
            print(f"📨 Datos recibidos: {nombre}, {email}, {mensaje}")
            
            if not nombre or not email or not mensaje:
                flash('Por favor, completa todos los campos.', 'error')
                return render_template('contact.html')
            
            if len(nombre) < 2:
                flash('El nombre debe tener al menos 2 caracteres.', 'error')
                return render_template('contact.html')
            
            if len(mensaje) < 10:
                flash('El mensaje debe tener al menos 10 caracteres.', 'error')
                return render_template('contact.html')
            
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        'INSERT INTO contactos (nombre, email, mensaje, ip_cliente) VALUES (%s, %s, %s, %s)',
                        (nombre, email, mensaje, ip_cliente)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    flash('¡Mensaje enviado correctamente! Nos pondremos en contacto contigo pronto.', 'success')
                    print("✅ Mensaje guardado en la base de datos MySQL")
                except Exception as e:
                    print(f"❌ Error insertando en la base de datos MySQL: {e}")
                    flash('Error al enviar el mensaje. Por favor, intenta nuevamente.', 'error')
            else:
                print("❌ No se pudo conectar a la base de datos MySQL")
                flash('Error de conexión con la base de datos. Por favor, intenta más tarde.', 'error')
            
            return redirect(url_for('contact'))
            
        except Exception as e:
            print(f"❌ Error general en el formulario: {e}")
            flash('Error inesperado. Por favor, intenta nuevamente.', 'error')
            return redirect(url_for('contact'))
    
    return render_template("contact.html")

@app.route("/blog")
def blog():
    return render_template("blog.html")

@app.route("/nosotros")
def nosotros():
    return render_template("nosotros.html")

@app.route("/formulario_compra", methods=['GET', 'POST'])
def formulario_compra():
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            nombre = request.form.get('full-name')
            email = request.form.get('email')
            telefono = request.form.get('phone')
            direccion = request.form.get('address')
            metodo_pago = request.form.get('payment-method')
            datos_carrito = request.form.get('cart-data')
            total = request.form.get('total')
            
            print(f"📝 DATOS DEL FORMULARIO:")
            print(f"   Nombre: {nombre}")
            print(f"   Email: {email}")
            print(f"   Teléfono: {telefono}")
            print(f"   Dirección: {direccion}")
            print(f"   Método pago: {metodo_pago}")
            print(f"   Total: {total}")
            print(f"   Carrito: {datos_carrito}")
            
            # Validar datos requeridos
            if not all([nombre, email, telefono, direccion, metodo_pago, datos_carrito, total]):
                missing = []
                if not nombre: missing.append('nombre')
                if not email: missing.append('email')
                if not telefono: missing.append('teléfono')
                if not direccion: missing.append('dirección')
                if not metodo_pago: missing.append('método de pago')
                if not datos_carrito: missing.append('carrito')
                if not total: missing.append('total')
                
                flash(f'Faltan campos: {", ".join(missing)}', 'error')
                return render_template("formulario_compra.html")
            
            # Si el usuario está autenticado, usar su ID, sino NULL
            usuario_id = current_user.id if current_user.is_authenticated else None
            print(f"   Usuario ID: {usuario_id}")
            
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    
                    # Insertar el pedido con la nueva estructura
                    cursor.execute(
                        '''INSERT INTO pedidos 
                        (usuario_id, nombre_cliente, email_cliente, telefono_cliente, 
                         direccion_cliente, metodo_pago, total, datos_pedido) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                        (usuario_id, nombre, email, telefono, direccion, metodo_pago, total, datos_carrito)
                    )
                    
                    # Obtener ID del pedido creado
                    pedido_id = cursor.lastrowid
                    
                    # Si el usuario está autenticado, agregar puntos
                    if current_user.is_authenticated:
                        puntos_ganados = agregar_puntos(current_user.id, float(total))
                        mensaje = f'¡Pedido #{pedido_id} realizado con éxito! Ganaste {puntos_ganados} puntos.'
                    else:
                        mensaje = f'¡Pedido #{pedido_id} realizado con éxito! Te contactaremos pronto.'
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    flash(mensaje, 'success')
                    print(f"✅ Pedido #{pedido_id} guardado correctamente en la base de datos")
                    
                    # Limpiar el carrito después del pedido exitoso
                    # Esto se manejaría en el frontend con JavaScript
                    
                    return redirect(url_for('index'))
                    
                except Exception as e:
                    print(f"❌ Error guardando pedido en la base de datos: {e}")
                    flash('Error al procesar el pedido. Intenta nuevamente.', 'error')
            else:
                print("❌ No se pudo conectar a la base de datos")
                flash('Error de conexión con la base de datos. Por favor, intenta más tarde.', 'error')
                
        except Exception as e:
            print(f"❌ Error general en formulario de compra: {e}")
            flash('Error al procesar el formulario. Intenta nuevamente.', 'error')
    
    return render_template("formulario_compra.html")

@app.route("/compra_productos")
def compra_productos():
    categoria = request.args.get('categoria', 'magnesicos')
    return render_template("compra_productos.html", categoria=categoria)

@app.route("/test-db")
def test_db():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM contactos")
            count = cursor.fetchone()[0]
            cursor.execute("SELECT * FROM contactos ORDER BY id DESC LIMIT 1")
            last_message = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            result = f"✅ Conexión exitosa a MySQL. Hay {count} mensajes en la base de datos."
            if last_message:
                result += f"<br>Último mensaje: {last_message[1]} - {last_message[2]}"
            return result
        except Exception as e:
            return f"❌ Error en la consulta MySQL: {e}"
    else:
        return "❌ No se pudo conectar a la base de datos MySQL"

if __name__ == '__main__':
    app.run(debug=True)