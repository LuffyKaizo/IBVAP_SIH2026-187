/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AI_SERVICE_URL: string;
  readonly VITE_SCREENING_MODE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
