# Captura Gemini USB

Version principal de la app para enviar capturas a Gemini y abrir la respuesta en `informacion.txt`.

## Flujo

- Modo recomendado sin admin: abre la app, toma la captura con `Fn+Impr` o `ImprPant`, guarda la imagen y la app la detecta sola
- Atajo global en GNOME: `Ctrl+Alt+G`
- Atajo con la terminal enfocada: `F8` para captura directa opcional
- Resultado: se guarda en `informacion.txt` y se abre con el editor del sistema

## Requisitos en Debian

- `python3`
- No hace falta instalar capturadores del sistema si usas el modo recomendado con `Fn+Impr`

## Arranque

- Doble clic en `Iniciar Captura Gemini.desktop`
- Si no funciona el doble clic: `bash ./INICIAR.sh`
- Prueba de solo captura: `bash ./INICIAR.sh --self-test-capture`
- Prueba de deteccion de capturas guardadas: `bash ./INICIAR.sh --self-test-watch`

## Configuracion

1. Copia `.env.example` a `.env`
2. Agrega tu clave:

```bash
GEMINI_API_KEY=tu_clave
GEMINI_MODEL=gemini-3-pro-preview
```

Si dejas `GEMINI_API_KEY=__SET_ME__`, la app la pedira al iniciar y la guardara en `.env`.

## Modo sin administrador

1. Abre la app.
2. Dejala abierta.
3. Toma la captura con `Fn+Impr` o `ImprPant`.
4. Guarda la imagen en la carpeta normal de capturas del sistema.
5. La app detecta el archivo, lo envia sola y luego lo borra automaticamente.

## Si GNOME no deja ejecutar desde la USB

- Doble clic en `Instalar Captura Gemini.desktop`
- O ejecuta: `bash ./INSTALAR.sh`

Eso copia la app a `~/.local/share/captura_gemini_usb/`, crea un lanzador local y deja configurado el atajo global en GNOME cuando es posible.

## Captura directa opcional

Si alguna computadora ya tiene `gnome-screenshot`, `grim`, `scrot`, `maim` o `import`, puedes usar `F8` o `r + Enter` para intentar una captura directa desde la app.
