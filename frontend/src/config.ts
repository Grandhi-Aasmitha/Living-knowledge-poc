const DEFAULT_API_ROOT = 'http://localhost:8000';

export const API_ROOT = import.meta.env.VITE_API_ROOT ?? DEFAULT_API_ROOT;
export const ASSISTANT_MAX_QUESTION_LENGTH = 1000;
