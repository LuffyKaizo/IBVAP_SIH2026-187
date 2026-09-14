/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AI_SERVICE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
