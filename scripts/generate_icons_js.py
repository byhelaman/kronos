#!/usr/bin/env python3
"""
Script para generar icons.js desde icons.html
Mantiene ambos archivos sincronizados automáticamente
"""

import re
import json
from pathlib import Path

def extract_icons_from_html(html_file):
    """Extrae las definiciones de iconos del archivo HTML"""
    icons = {}
    
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Patrón para encontrar macros de iconos
    pattern = r'{%\s*macro\s+(\w+Icon)\(size=24\)\s*-%}(.*?){%-\s*endmacro\s*%}'
    
    matches = re.finditer(pattern, content, re.DOTALL)
    
    for match in matches:
        icon_name = match.group(1)
        svg_content = match.group(2).strip()
        
        # Extraer paths y elementos del SVG
        paths = []
        stroke_width = "2"
        class_name = ""
        
        # Extraer stroke-width si existe
        stroke_width_match = re.search(r'stroke-width="([^"]+)"', svg_content)
        if stroke_width_match:
            stroke_width = stroke_width_match.group(1)
        
        # Extraer class
        class_match = re.search(r'class="([^"]+)"', svg_content)
        if class_match:
            class_name = class_match.group(1)
        
        # Extraer todos los elementos (path, circle, line, polyline, rect)
        # Buscar elementos auto-cerrados
        element_pattern = r'<(path|circle|line|polyline|rect)([^>]*?)\s*/>'
        elements = re.finditer(element_pattern, svg_content)
        
        for elem in elements:
            elem_type = elem.group(1)
            elem_attrs = elem.group(2).strip()
            # Limpiar espacios extra y reconstruir el elemento
            if elem_attrs:
                elem_attrs = ' '.join(elem_attrs.split())  # Normalizar espacios
                paths.append(f"<{elem_type} {elem_attrs} />")
            else:
                paths.append(f"<{elem_type} />")
        
        icons[icon_name] = {
            "paths": paths,
            "strokeWidth": stroke_width,
            "class": class_name
        }
    
    return icons

def generate_js_file(icons, output_file):
    """Genera el archivo icons.js desde las definiciones"""
    
    js_content = """/**
 * Módulo de iconos SVG centralizado
 * GENERADO AUTOMÁTICAMENTE desde icons.html
 * NO EDITAR MANUALMENTE - Ejecutar scripts/generate_icons_js.py para regenerar
 */

export const Icons = {
"""
    
    # Generar funciones para cada icono
    for icon_name, icon_data in sorted(icons.items()):
        # Convertir nombre de macro a nombre de función
        # LoaderIcon -> loader, CheckIcon -> check, etc.
        func_name = icon_name.replace('Icon', '')
        func_name = func_name[0].lower() + func_name[1:] if func_name else func_name.lower()
        
        # Mapeos especiales
        name_mapping = {
            'loader': 'loader',
            'alertTriangle': 'alertTriangle',
            'user': 'user',
            'calendarCog': 'calendarCog',
            'restore': 'restore',
            'link': 'link',
            'radio': 'radio',
            'chevronRight': 'chevronRight',
            'chevronLeft': 'chevronLeft',
            'upload': 'upload',
            'bot': 'bot',
            'send': 'send',
            'file': 'file',
            'trash': 'trash',
            'corner': 'corner',
            'split': 'split',
            'download': 'download',
            'settings': 'settings',
            'search': 'search',
            'fileUp': 'fileUp',
            'sun': 'sun',
            'moon': 'moon',
            'check': 'check',
            'alertCircle': 'alertCircle',
            'info': 'info',
            'x': 'x'
        }
        
        func_name = name_mapping.get(func_name, func_name)
        
        # Construir el SVG
        paths_str = '\n    '.join(icon_data['paths'])
        stroke_width = icon_data.get('strokeWidth', '2')
        class_name = icon_data.get('class', '').replace('lucide ', '').strip()  # Remover duplicados
        
        js_content += f"""  /**
   * Genera un SVG de {icon_name.replace('Icon', '')}
   */
  {func_name}(size = 24) {{
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${{size}}" height="${{size}}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round" class="lucide {class_name}">
    {paths_str}
</svg>`;
  }},

"""
    
    js_content += """};

// Exportar también como default para compatibilidad
export default Icons;
"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(js_content)
    
    print(f"[OK] Generado {output_file}")

def main():
    """Función principal"""
    base_dir = Path(__file__).parent.parent
    html_file = base_dir / "templates" / "macros" / "icons.html"
    js_file = base_dir / "static" / "js" / "icons.js"
    
    if not html_file.exists():
        print(f"Error: No se encontró {html_file}")
        return
    
    print(f"Leyendo {html_file}...")
    icons = extract_icons_from_html(html_file)
    
    print(f"Encontrados {len(icons)} iconos")
    print(f"Generando {js_file}...")
    generate_js_file(icons, js_file)
    
    print("[OK] Proceso completado")

if __name__ == "__main__":
    main()

