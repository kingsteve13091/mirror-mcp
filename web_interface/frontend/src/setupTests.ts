import '@testing-library/jest-dom';

// React 18 async effects need an explicit act-capable test environment flag.
// Without this, harmless state updates from boot-time async loaders emit noisy
// warnings and can destabilize component tests.
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
