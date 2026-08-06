# Login Network uses CDN Three.js WebGL shader on Portal login

Portal stays vanilla HTML/CSS/JS (no React/shadcn). Login Network keeps its product meaning as the login-hero decorative atmosphere, but the implementation is a WebGL fragment shader loaded via CDN Three.js only while the login shell is active. We rejected scaffolding a React frontend for one effect, rejected keeping a second canvas-2D implementation as fallback, and chose silent degrade (same as `prefers-reduced-motion`) when WebGL or the CDN fails. Theme tints the shader; mouse interactivity is not required.
