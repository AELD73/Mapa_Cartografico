# Guía de Despliegue para Administrador de Sistemas (SysAdmin)

**Proyecto:** Mapa Cartográfico (Flask + SQLite)
**Servidor Destino:** `siapi` (Ubuntu/Debian)
**Usuario del aplicativo:** `usrlabesturb`
**Ruta del aplicativo:** `/var/www/html/labestudiosurbanos/Mapa_Cartografico`
**Ruta de Binarios (Python):** `/var/www/html/labestudiosurbanos/.local/bin`
**Dominio:** `labestudiosurbanos.azc.uam.mx`

---

Estimado Administrador de Sistemas:
La aplicación web y todas sus dependencias (Flask, Gunicorn, Pandas, etc.) ya se encuentran instaladas correctamente a nivel de usuario (en el directorio unverified `.local` del usuario `usrlabesturb`). Debido a requerimientos de permisos (`sudo`), necesitamos de su apoyo para configurar el demonio de Gunicorn y el proxy inverso en Apache para exponer la aplicación de manera segura al exterior con HTTPS.

A continuación los comandos paso a paso para la puesta en marcha.

## 1. Crear el Servicio de Systemd para Gunicorn
Gunicorn es responsabilidad de mantener viva la aplicación localmente en el puerto `8000`.
Cree el archivo del servicio:
```bash
sudo nano /etc/systemd/system/mapa.service
```

Bloque de texto a pegar dentro del archivo:
```ini
[Unit]
Description=Demonio de Gunicorn - Mapa Cartografico
After=network.target

[Service]
User=usrlabesturb
Group=www-data
WorkingDirectory=/var/www/html/labestudiosurbanos/Mapa_Cartografico
Environment="PATH=/var/www/html/labestudiosurbanos/.local/bin"
# Inicia gunicorn con 3 workers internos usando los binarios del usuario
ExecStart=/var/www/html/labestudiosurbanos/.local/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 app:app

[Install]
WantedBy=multi-user.target
```

Guardar cambios e iniciar el servicio:
```bash
sudo systemctl daemon-reload
sudo systemctl start mapa
sudo systemctl enable mapa
```
*(Validar estatus asegurando que corre sin errores con estado verde: `sudo systemctl status mapa`)*

---

## 2. Configurar el Servidor Apache (Proxy Inverso)
Las peticiones que lleguen por web deben ser encapsuladas y redirigidas a Gunicorn.
Asegurar que los módulos de redirección estén activos:
```bash
sudo a2enmod proxy
sudo a2enmod proxy_http
```

Crear el Virtual Host HTTP básico para atrapar las entradas públicas (antes del SSL):
```bash
sudo nano /etc/apache2/sites-available/mapa.conf
```

Pegue el siguiente bloque:
```apache
<VirtualHost *:80>
    ServerName labestudiosurbanos.azc.uam.mx

    # Redireccionamiento interno al puerto de Flask
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Archivos de registro
    ErrorLog ${APACHE_LOG_DIR}/mapa-error.log
    CustomLog ${APACHE_LOG_DIR}/mapa-access.log combined
</VirtualHost>
```

Activar el sitio en Apache y reiniciar:
```bash
sudo a2ensite mapa.conf
sudo systemctl reload apache2
```

---

## 3. Instalación de SSL (Certbot HTTPS)
Instalar herramienta oficial de Let's Encrypt si no está disponible:
```bash
sudo apt update
sudo apt install certbot python3-certbot-apache
```

Levantar y asignar el certificado al dominio recién creado:
```bash
sudo certbot --apache -d labestudiosurbanos.azc.uam.mx
```
*(Durante el prompt, aceptar redirecciones automáticas/Forzar HTTPS si Certbot lo pregunta).*

Reiniciar apache para asentar cambios finales:
```bash
sudo systemctl restart apache2
```

La página deberá encontrarse funcional en `https://labestudiosurbanos.azc.uam.mx/`.
