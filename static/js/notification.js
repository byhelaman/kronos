/**
 * Sistema de notificaciones mejorado para la aplicación
 * Reemplaza los alert() nativos con notificaciones visuales modernas
 */

import { Icons } from "./icons.js";

class NotificationManager {
    constructor() {
        this.container = null;
        this.notifications = new Map();
        // this.defaultDuration = 5000; // 5 segundos
        this.init();
    }

    init() {
        // Crear contenedor de notificaciones si no existe
        if (!this.container) {
            this.container = document.createElement("div");
            this.container.className = "notification-container";
            this.container.setAttribute("aria-live", "polite");
            this.container.setAttribute("aria-atomic", "true");
            document.body.appendChild(this.container);
        }
    }

    /**
     * Muestra una notificación
     * @param {string} message - Mensaje a mostrar
     * @param {string} type - Tipo: 'success', 'error', 'warning', 'info'
     * @param {Object} options - Opciones adicionales
     * @param {number} options.duration - Duración en ms (0 = no auto-cerrar)
     * @param {boolean} options.dismissible - Si se puede cerrar manualmente
     */
    show(message, type = "info", options = {}) {
        const {
            duration = this.defaultDuration,
            dismissible = true,
        } = options;

        const notification = this.createNotification(message, type, dismissible);
        this.container.appendChild(notification);

        // Animar entrada
        requestAnimationFrame(() => {
            notification.classList.add("notification--show");
        });

        const notificationId = Date.now() + Math.random();
        this.notifications.set(notificationId, notification);

        // Auto-cerrar si tiene duración
        if (duration > 0) {
            const timeoutId = setTimeout(() => {
                this.remove(notificationId);
            }, duration);
            notification._timeoutId = timeoutId;
        }

        return notificationId;
    }

    createNotification(message, type, dismissible) {
        const notification = document.createElement("div");
        notification.className = `notification notification--${type}`;
        notification.setAttribute("role", "alert");

        // Icono según el tipo
        const icon = this.getIcon(type);

        // Contenido
        const content = document.createElement("div");
        content.className = "notification__content";
        content.innerHTML = `
      <span class="notification__icon">${icon}</span>
      <span class="notification__message">${this.escapeHtml(message)}</span>
    `;

        notification.appendChild(content);

        // Botón de cerrar si es dismissible
        if (dismissible) {
            const closeBtn = document.createElement("button");
            closeBtn.className = "notification__close";
            closeBtn.setAttribute("aria-label", "Cerrar notificación");
            closeBtn.innerHTML = Icons.x(16);
            closeBtn.addEventListener("click", () => {
                const notificationId = Array.from(this.notifications.entries()).find(
                    ([_, notif]) => notif === notification
                )?.[0];
                if (notificationId) {
                    this.remove(notificationId);
                }
            });
            notification.appendChild(closeBtn);
        }

        return notification;
    }

    getIcon(type) {
        const iconMap = {
            success: Icons.check(20),
            error: Icons.alertCircle(20),
            warning: Icons.alertTriangle(20),
            info: Icons.info(20),
        };
        return iconMap[type] || iconMap.info;
    }

    remove(notificationId) {
        const notification = this.notifications.get(notificationId);
        if (!notification) return;

        // Limpiar timeout si existe
        if (notification._timeoutId) {
            clearTimeout(notification._timeoutId);
        }

        // Animar salida
        notification.classList.remove("notification--show");
        notification.classList.add("notification--hide");

        // Remover del DOM después de la animación
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
            this.notifications.delete(notificationId);
        }, 300);
    }

    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    // Métodos de conveniencia
    success(message, options = {}) {
        return this.show(message, "success", options);
    }

    error(message, options = {}) {
        return this.show(message, "error", options);
    }

    warning(message, options = {}) {
        return this.show(message, "warning", options);
    }

    info(message, options = {}) {
        return this.show(message, "info", options);
    }
}

// Crear instancia global
const notificationManager = new NotificationManager();

// Exportar para uso en módulos ES6
export { NotificationManager, notificationManager };

// También hacer disponible globalmente para compatibilidad
window.NotificationManager = NotificationManager;
window.notificationManager = notificationManager;

