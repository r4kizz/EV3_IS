"""
URL configuration for Almacen project.
"""
from django.urls import path
from usuarios import caja, ingresos, inventario, proveedores, views

urlpatterns = [
    path("accounts/login/", views.iniciar_sesion, name="login"),
    path("accounts/logout/", views.cerrar_sesion, name="logout"),
    path("usuarios/nuevo/", views.nuevo_usuario, name="nuevo_usuario"),
    path("inventario/", inventario.productos, name="inventario"),
    path("inventario/<int:id_producto>/editar/", inventario.productos, name="editar_producto"),
    path("inventario/<int:id_producto>/eliminar/", inventario.eliminar_producto, name="eliminar_producto"),
    path("", views.inicio, name="inicio"),
    path("caja/", views.vista_caja, name="caja"),
    path("caja/confirmar-venta/", views.api_confirmar_venta, name="api_confirmar_venta"),
    
    # Proveedores
    path("proveedores/", proveedores.proveedores, name="proveedores"),
    path("proveedores/<int:id_proveedor>/editar/", proveedores.proveedores, name="editar_proveedor"),
    path("proveedores/<int:id_proveedor>/eliminar/", proveedores.eliminar_proveedor, name="eliminar_proveedor"),

    # Facturas e Ingreso de Mercadería
    path("ingresos/", ingresos.historial_ingresos, name="ingresos"),
    path("ingresos/nuevo/", ingresos.nuevo_ingreso, name="nuevo_ingreso"),
    path("ingresos/confirmar/", ingresos.api_confirmar_ingreso, name="api_confirmar_ingreso"),
    path("ingresos/<int:id_ingreso>/detalle/", ingresos.detalle_ingreso_view, name="detalle_ingreso"),
]
