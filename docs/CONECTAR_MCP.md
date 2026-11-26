# Conectar Agente Tutor Persistente vía MCP (v2.0)

Este servidor implementa los **3 pilares oficiales de MCP** (`25 Tools`, `8 Resources` y `7 Prompts`) y funciona tanto en **local (`stdio`)** como en **remoto (`Streamable HTTP` en `/mcp`)**.

---

## 1. Instalación rápida en local (`stdio`)

```powershell
# Desde la raíz del repositorio
pip install --no-build-isolation -e .

# Probar arranque del CLI
agente-tutor-mcp --help
```

También puedes ejecutarlo sin instalar usando tu entorno virtual:
`python -m app.mcp_tools`

---

## 2. Configuración por cliente (copiar y pegar)

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "agente-tutor": {
      "command": "C:/Users/POWER/Documents/GitHub/agente-tutor-persistente/.venv/Scripts/python.exe",
      "args": ["-m", "app.mcp_tools"],
      "env": {
        "DATABASE_URL": "sqlite:///C:/Users/POWER/Documents/GitHub/agente-tutor-persistente/tutor.db",
        "GEMINI_API_KEY": ""
      }
    }
  }
}
```

### Claude Code / Cursor / Antigravity (local `stdio`)
```json
{
  "mcpServers": {
    "agente-tutor": {
      "command": "agente-tutor-mcp",
      "env": {
        "DATABASE_URL": "sqlite:///./tutor.db"
      }
    }
  }
}
```

### Conexión remota (Render — `Streamable HTTP`)
```json
{
  "mcpServers": {
    "agente-tutor-remoto": {
      "url": "https://<tu-servicio>.onrender.com/mcp",
      "headers": {
        "Authorization": "Bearer <TU_TUTOR_TOKEN>"
      }
    }
  }
}
```

---

## 3. Qué puedes pedirle a tu IDE conectado

- **Aprender el código que acaban de construir**: *«Usa `estudiar_codigo` con esta función que creamos y guárdala en la colección FastAPI»*.
- **Convertir apuntes en fichas**: *«Usa `ingestar_material` con estas notas de clase»*.
- **Repasar con SM-2**: *«Ejecuta el prompt `sesion_repaso`»* o *«Revisa `tutor://brechas` y hazme un diagnóstico»*.
