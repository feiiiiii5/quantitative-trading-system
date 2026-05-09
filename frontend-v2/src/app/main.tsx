import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { QueryProvider } from '@/app/providers/QueryProvider';
import { WSProvider } from '@/app/providers/WSProvider';
import { ThemeProvider } from '@/app/providers/ThemeProvider';
import { ToastProvider } from '@/shared/ui';
import { router } from '@/app/router';
import '@/app/styles/tokens.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryProvider>
      <ThemeProvider>
        <WSProvider>
          <ToastProvider>
            <RouterProvider router={router} />
          </ToastProvider>
        </WSProvider>
      </ThemeProvider>
    </QueryProvider>
  </StrictMode>
);
