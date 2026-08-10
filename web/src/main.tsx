import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@mantine/core/styles.css';
import './styles.css';
import App from './App';

const root = document.getElementById('root');
if (root === null) {
  throw new Error('Root element #root not found.');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
