/**
 * Sistema de notificaciones mejorado para la aplicación
 * Reemplaza los alert() nativos con notificaciones visuales modernas
 */

import { Icons } from "./icons.js";

class NotificationManager {
    constructor() {
        this.container = null;
        this.notifications = new Map();
        this.defaultDuration = 10000; // 5 segundos
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
     * @param {string|Object} messageOrConfig - Mensaje a mostrar o objeto con {title, message}
     * @param {string} type - Tipo: 'success', 'error', 'warning', 'info'
     * @param {Object} options - Opciones adicionales
     * @param {number} options.duration - Duración en ms (0 = no auto-cerrar)
     * @param {boolean} options.dismissible - Si se puede cerrar manualmente
     */
    show(messageOrConfig, type = "info", options = {}) {
        const {
            duration = this.defaultDuration,
            dismissible = true,
        } = options;

        // Soporte para formato antiguo (solo mensaje) y nuevo (objeto con title/message)
        let title, message;
        if (typeof messageOrConfig === "string") {
            title = messageOrConfig;
            message = null;
        } else {
            title = messageOrConfig.title || messageOrConfig.message;
            message = messageOrConfig.message || null;
        }

        const notification = this.createNotification(title, message, type, dismissible);
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

    createNotification(title, description, type, dismissible) {
        const notification = document.createElement("div");
        notification.className = `notification notification--${type}`;
        notification.setAttribute("role", "alert");

        // Icono según el tipo
        const icon = this.getIcon(type);

        // Contenido principal
        const content = document.createElement("div");
        content.className = "notification__content";

        // Header con icono y título
        const header = document.createElement("div");
        header.className = "notification__header";

        const iconSpan = document.createElement("span");
        iconSpan.className = "notification__icon";
        iconSpan.innerHTML = icon;

        const titleSpan = document.createElement("span");
        titleSpan.className = "notification__title";
        titleSpan.textContent = title;

        header.appendChild(iconSpan);
        header.appendChild(titleSpan);
        content.appendChild(header);

        // Descripción si existe
        if (description) {
            const messageDiv = document.createElement("div");
            messageDiv.className = "notification__message";
            // Permitir HTML en la descripción para soportar listas
            if (description.includes("<ul>") || description.includes("<li>")) {
                messageDiv.innerHTML = description;
            } else {
                messageDiv.textContent = description;
            }
            content.appendChild(messageDiv);
        }

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
    success(messageOrConfig, options = {}) {
        return this.show(messageOrConfig, "success", options);
    }

    error(messageOrConfig, options = {}) {
        return this.show(messageOrConfig, "error", options);
    }

    warning(messageOrConfig, options = {}) {
        return this.show(messageOrConfig, "warning", options);
    }

    info(messageOrConfig, options = {}) {
        return this.show(messageOrConfig, "info", options);
    }
}

// Crear instancia global
const notificationManager = new NotificationManager();

// Exportar para uso en módulos ES6
export { NotificationManager, notificationManager };

// También hacer disponible globalmente para compatibilidad
window.NotificationManager = NotificationManager;
window.notificationManager = notificationManager;

