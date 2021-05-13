
import subprocess
import logging
from os import pipe, remove

from program.controllers import containers
import dependencies.register.register as register
from dependencies.lxc_classes.container import Container
from dependencies.utils.lxc_functions import (
    checkin_lxclist,
    lxclist_as_dict
)
from program.platform.machines import servers

# ---------------------- BALANCEADOR DE CARGA ------------------------
# --------------------------------------------------------------------
# Este fichero se encarga de proporcionar funciones para crear y 
# configurar el objeto del balanceador de carga que se va a utilizar
# en la plataforma
# --------------------------------------------------------------------

lb_logger = logging.getLogger(__name__)
# Tag e id de registro para la imagen configurada
TAG = "load balancer"; IMG_ID = "lb_image" 
# Algoritmo de balanceo de trafico
default_algorithm = "roundrobin"
# Puerto para que se conecte el cliente
PORT = 80
# Imagen por defecto sobre la que se va a realizar la configuracion
default_image = "ubuntu:18.04"
# --------------------------------------------------------------------
def get_lb(image:str=None, balance=None) -> Container:
    """Devuelve el objeto del LB configurado

    Args:
        image (str, optional): imagen del contenedor a usar.
            Si es None, crea una imagen propia para el balanceador
            configurada y funcional (permite actuar al contenedor 
            como un balanceador de trafico)

    Returns:
        Container: objeto del balanceador de carga configurado
    """
    # Comprobamos que si hace falta configurar una imagen base para
    # el balanceador o ya se ha creado antes y esta disponible
    if image == None:
        img_saved = register.load(IMG_ID)
        if img_saved is None:
            image = _config_image()
        else:
            # Comprobamos que la imagen no se haya borrado en lxc
            fgp = img_saved["fingerprint"]
            msg = f" Imagen anterior guardada del balanceador '{fgp}'"
            lb_logger.debug(msg)
            if checkin_lxclist(["lxc", "image", "list"], 1, fgp):
                # Vemos el alias de la imagen por si se ha modificado 
                process = subprocess.run(
                    ["lxc","image","list"],
                    stdout=subprocess.PIPE
                )
                lista = process.stdout.decode()
                images = lxclist_as_dict(lista)
                headers = list(images.keys())
                alias = ""
                for i, fg in enumerate(images[headers[1]]):
                    if fg == fgp:
                        alias = images[headers[0]][i]
                        break
                image_info = {"alias": alias, "fingerprint": fgp}
                register.update(IMG_ID, image_info, override=True)
                image = alias
                if alias == "": image = fgp
                msg = f" Alias actual de la imagen del lb -> '{alias}'"
                lb_logger.debug(msg)
            else:
                # Como se ha eliminado creamos otra nueva
                msg = (f" Imagen del balanceador se ha borrado" + 
                        "desde fuera del programa")
                lb_logger.debug(msg)
                register.remove(IMG_ID)
                image = _config_image()
    if balance is None:
        balance = default_algorithm
    # Creamos el balanceador
    msg = (f" Creando balanceador con imagen '{image}' " + 
           f"y algoritmo de balanceo '{balance}'")
    lb_logger.debug(msg)
    lb = Container("lb", image, tag=TAG)
    lb.add_to_network("eth0", "10.0.0.10")
    lb.add_to_network("eth1", "10.0.1.10")
    
    setattr(lb, "algorithm", balance)
    return lb

# --------------------------------------------------------------------
def _config_image() -> str:
    """Crea una imagen para el balanceador de carga completamente
    configurada y funcional a partir de la default_image

    Returns:
        str: alias de la imagen creada
    """
    lb_logger.info(" Creando la imagen base del balanceador...")
    # Vemos que no haya un contenedor con ese nombre ya
    name = "lbconfig"
    j = 1
    while checkin_lxclist(["lxc", "list"], 0, name):
        name = f"lbconfig{j}"
        j += 1
    msg = f" Contenedor usado para crear la imagen del lb -> '{name}'"
    lb_logger.debug(msg)
    lb_c = Container(name, default_image)
    # Lanzamos el contenedor e instalamos haproxy
    lb_logger.info(f" Lanzando '{name}'...")
    lb_c.init(); lb_c.start()
    lb_logger.info(" Instalando haproxy (puede tardar)...")
    lb_c.wait_for_startup()
    process = subprocess.run(
        ["lxc","exec",name,"--","apt","update"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    process = subprocess.run(
        ["lxc","exec",name,"--","apt","install","-y","haproxy"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    if process.returncode == 0:
        lb_logger.info(" Haproxy instalado con exito")
        lb_logger.info(" Iniciando haproxy...")
        subprocess.run(
            ["lxc","exec",name,"--","service","haproxy","start"]
        ) 
        lb_logger.info(" Haproxy iniciado")  
    else:
        lb_logger.error(" Fallo al instalar haproxy")
    # Configuramos el netfile
    lb_c.add_to_network("eth0", "10.0.0.10")
    lb_c.add_to_network("eth1", "10.0.1.10")
    containers.configure_netfile(lb_c)
    # Vemos que no existe una imagen con el alias que vamos a usar
    alias = "haproxy_lb"
    k = 1
    while checkin_lxclist(["lxc", "image", "list"], 0, alias):
        alias = f"haproxy_lb{k}"
        k += 1
    # Una vez el alias es valido publicamos la imagen
    msg = f" Publicando la imagen del lb con alias '{alias}'..."
    lb_logger.info(msg)
    lb_c.stop()
    process = subprocess.run(
        ["lxc", "publish", name, "--alias", alias],
        stdout=subprocess.PIPE
    )
    lb_logger.info(" Imagen base del balanceador creada\n")
    # Eliminamos el contenedor
    lb_c.delete()
    # Guardamos la imagen en el registro y la devolvemos
    process = subprocess.run(
        ["lxc","image","list"],
        stdout=subprocess.PIPE
    )
    images = lxclist_as_dict(process.stdout.decode())
    headers = list(images.keys())
    fingerprint = ""
    for i, al in enumerate(images[headers[0]]):
        if al == alias:
            fingerprint = images[headers[1]][i]
    image_info = {"alias": alias, "fingerprint": fingerprint}
    register.add(IMG_ID, image_info)
    return alias

# --------------------------------------------------------------------
def update_haproxycfg():
    # Miramos si existen contenedores creados
    cs = register.load(containers.ID)
    if cs is None: return
    # Si se ha borrado el balanceador desde fuera del programa o no
    # se encuentra arrancado para actualizar salimos
    lb = None
    for c in cs:
        if c.tag == TAG:
            lb = c
    if lb is None: return
    # Miramos si el lb esta arrancado para actualizar (si no lo 
    # haremos la proxima vez que arranque) y si lo esta esperamos
    # a que termine el startup
    if lb.state != "RUNNING":
        return
    # Actualizamos el fichero
    lb_logger.info(" Actualizando el fichero haproxy del balanceador...")
    lb_logger.info(" Esperando startup del balanceador...")
    c.wait_for_startup()
    lb_logger.info(" Startup finalizado")
    # Procedemos a configurar el fichero de haproxy
    config = (
         "\n\nfrontend firstbalance\n" +
        f"        bind *:{PORT}\n" +
         "        option forwardfor\n" +
         "        default_backend webservers\n" +
         "backend webservers\n" +
        f"        balance {lb.algorithm}\n"
    )
    servs = list(filter(
        lambda c: c.tag == servers.TAG and c.state == "RUNNING",
        cs
    ))
    for i, s in enumerate(servs):
        l = f"        server webserver{i+1} {s.name}:{servers.PORT}\n"
        config += l
    for i, s in enumerate(servs):
        l = f"        server webserver{i+1} {s.name}:{servers.PORT} check\n"
        config += l
    config += "        option httpchk"
    lb_logger.debug(config)
    path = "/etc/haproxy/haproxy.cfg"
    # Leemos la info basica del fichero basic_haproxy.cfg
    basicfile_path = "program/resources/base_haproxy.cfg"
    with open(basicfile_path, "r") as file:
        base_file = file.read()
    # Juntamos los ficheros
    configured_file = base_file + config
    # Creamos el fichero haproxy.cfg lo enviamos al contenedor y
    # eliminamos el fichero que ya no nos hace falta
    with open("haproxy.cfg", "w") as file:
        file.write(configured_file)
    subprocess.run(
        ["lxc", "file", "push", "haproxy.cfg", "lb/"+f"{path}"],
        stdout=subprocess.PIPE
    )
    process = subprocess.run(
         ["lxc", "exec", "lb", "--", "haproxy", "-f", path, "-c"],
         stdout=subprocess.PIPE,
         stderr=subprocess.PIPE
    )
    if process.returncode == 0:
        lb_logger.info(" Fichero haproxy actualizado con exito")
        subprocess.run(
            ["lxc","exec",lb.name,"--","service","haproxy","restart"],
            stdout=subprocess.PIPE
        )
    else: 
        err = process.stderr.decode()
        err_msg = f" Fallo al configurar el fichero haproxy: {err}" 
        lb_logger.error(err_msg)
    remove("haproxy.cfg")
# --------------------------------------------------------------------