/**
 * Inicializa notificaciones desde query params y mensajes inline
 * Este script se ejecuta después de que la página carga para convertir
 * mensajes del servidor en notificaciones modernas
 */

import { notificationManager } from "./notification.js";

document.addEventListener("DOMContentLoaded", () => {
  // Función para obtener parámetros de la URL
  function getQueryParam(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
  }

  // Detectar mensajes de éxito en query params
  const successParam = getQueryParam("success");
  if (successParam) {
    let message = "";

    // Mapeo de códigos de éxito a mensajes
    const successMessages = {
      user_created: "Usuario creado exitosamente.",
      user_deleted: "Usuario eliminado exitosamente.",
      zoom_linked: "Zoom account linked successfully!",
      zoom_unlinked: "Zoom account unlinked successfully!",
    };

    message = successMessages[successParam] || "Operación completada exitosamente.";

    notificationManager.success(message);

    // Limpiar la URL removiendo el parámetro success
    const url = new URL(window.location);
    url.searchParams.delete("success");
    window.history.replaceState({}, "", url);
  }

  // Detectar mensajes de error en query params
  const errorParam = getQueryParam("error");
  if (errorParam) {
    let message = "";

    // Mapeo de códigos de error a mensajes
    const errorMessages = {
      zoom_auth_failed: "Debes iniciar sesión antes de vincular tu cuenta de Zoom.",
      zoom_link_failed: "Zoom account linking failed. Please try again.",
    };

    // Si es un código conocido, usar el mensaje mapeado
    // Si no, usar el valor del parámetro directamente
    if (errorMessages[errorParam]) {
      message = errorMessages[errorParam];
    } else if (errorParam === "true" || errorParam === "1") {
      // Error genérico
      message = "Usuario o contraseña incorrectos.";
    } else {
      message = `Error: ${errorParam}`;
    }

    notificationManager.error(message);

    // Limpiar la URL removiendo el parámetro error
    const url = new URL(window.location);
    url.searchParams.delete("error");
    window.history.replaceState({}, "", url);
  }

  // Convertir mensajes inline (form-message) en notificaciones
  // Solo si NO hay query params (para evitar duplicados)
  // Si hay query params, ya se procesaron arriba
  if (!successParam && !errorParam) {
    const formMessages = document.querySelectorAll(".form-message");
    formMessages.forEach((msgEl) => {
      const message = msgEl.textContent.trim();

      if (msgEl.classList.contains("form-message--success")) {
        notificationManager.success(message);
      } else if (msgEl.classList.contains("form-message--error")) {
        notificationManager.error(message);
      } else if (msgEl.classList.contains("form-message--warning")) {
        notificationManager.warning(message);
      }

      // Ocultar el mensaje inline después de mostrar la notificación
      msgEl.style.display = "none";
    });

    // Convertir mensajes de error de formulario (form-error-message)
    const formErrorMessages = document.querySelectorAll(".form-error-message");
    formErrorMessages.forEach((msgEl) => {
      const message = msgEl.textContent.trim();
      notificationManager.error(message);
      msgEl.style.display = "none";
    });
  } else {
    // Si hay query params, ocultar los mensajes inline para evitar duplicados
    document.querySelectorAll(".form-message, .form-error-message").forEach((msgEl) => {
      msgEl.style.display = "none";
    });
  }

});

