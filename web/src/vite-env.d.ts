/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_QMIE_API?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
