# mouse-autoscroll

Autoscroll al estilo Windows con el botón central, para cualquier ratón, en todo el sistema (Linux, Wayland/X11; pensado para Hyprland).

- **Pulsar y soltar** el botón central: el modo se queda puesto. La página se desplaza más rápido cuanto más te alejas del punto de origen. **Cualquier clic** (o girar la rueda) lo termina, y ese clic no llega a la aplicación.
- **Mantener pulsado** y mover: se desplaza mientras lo mantienes y para al soltar.
- **Por aplicación** (clase de ventana de Hyprland):
  - `ignore`: no toca nada. Navegadores con autoscroll propio, juegos.
  - `hold`: un clic corto sigue siendo un clic central normal (pegar, abrir en pestaña nueva); solo mantener desplaza.
  - el resto: comportamiento completo.

## Cómo funciona

Un daemon en Python captura cada ratón real con evdev (`EVIOCGRAB`) y crea un clon virtual con uinput (`<nombre> (autoscroll)`). Todo lo que no es autoscroll pasa al clon sin cambios.

Mientras desplaza, el cursor se mueve libremente, como en Zen. La velocidad sale de su distancia real al origen, que pregunta a Hyprland. Para que la rueda no se vaya a otra ventana al pasar por encima, el clon mantiene pulsado `BTN_TASK`, un botón que casi ninguna app usa: mientras hay un botón pulsado, el compositor deja el foco del puntero en la ventana donde se pulsó. Si Hyprland no responde, o con `free_pointer = false`, el cursor se queda congelado en el origen.

**Qué cuenta como ratón:** lo decide lo que el dispositivo es y sabe hacer, no su nombre:
- udev lo marca como `ID_INPUT_MOUSE`;
- tiene botón central y movimiento relativo;
- no es trackpoint, touchpad, tableta ni joystick;
- no es un dispositivo virtual.

Se detectan al conectarlos (eventos de udev).

**Seguridad:**
- Si el daemon muere, el kernel suelta el grab y el ratón vuelve a la normalidad al instante.
- Si se cuelga, el watchdog de systemd (5 s) lo mata.
- El teclado nunca se captura, así que siempre puedes hacer `systemctl --user stop mouse-autoscroll`.

`indicator/` es un overlay de Quickshell aparte que dibuja el origen. Si se rompe, el scroll sigue funcionando.

## Instalación (Arch)

```sh
sudo pacman -S --needed python-evdev python-pyudev
sudo install -m644 udev/70-mouse-autoscroll.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input
ln -s "$PWD/bin/mouse-autoscroll" ~/.local/bin/mouse-autoscroll
mouse-autoscroll --list            # qué ratones cogería (no captura nada)
mouse-autoscroll -v --timeout 60   # prueba en primer plano; sale solo a los 60 s
ln -s "$PWD"/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mouse-autoscroll mouse-autoscroll-indicator
```

En Zen/Firefox activa el autoscroll nativo: `about:config` → `general.autoScroll` = `true`.

## Configuración

Es opcional: `~/.config/mouse-autoscroll/config.toml` (ver `config.example.toml`). Un archivo con errores no tumba el daemon: los valores malos se ignoran con un aviso en `journalctl --user -u mouse-autoscroll`.

## Problemas conocidos

- **LibreOffice, hacia arriba:** a veces el scroll hacia arriba se dispara a velocidades desproporcionadas, aunque el cursor se haya movido poco. Hacia abajo no pasa, ni en ninguna otra app (kitty, Obsidian…). El trazado (`--trace`) muestra que el daemon envía lo mismo en las dos direcciones, así que es cómo LibreOffice interpreta la rueda, no lo que se envía. No investigado más; dos hipótesis:
  - LibreOffice redondea cada trocito de rueda hacia arriba a una línea entera;
  - LibreOffice toma el botón `BTN_TASK` mantenido por un arrastre.

  Para distinguirlas, repetir con `free_pointer = false`: si deja de pasar, es el botón.
- **Fuera de la ventana el scroll se para** (cursor libre): mientras el cursor está encima de otra ventana no llega rueda a ninguna; al volver, sigue.

## Tests

```sh
python -m unittest discover -s tests -t .
```

La lógica (máquina de estados, curva, modos, configuración, IPC, selección de dispositivos) se prueba sin hardware. La captura real del ratón se prueba a mano.
