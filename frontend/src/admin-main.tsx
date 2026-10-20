import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { ToastProvider } from './components/ui';
import AdminApp from './pages/admin/AdminApp';
import './fonts';
import './index.css';

/** The admin console: a static SPA of its own (admin.html, vite.admin.config.ts), served on
 *  ADMIN_HOST under a strict CSP and never rendered on the server. The site's pages are not part
 *  of it: anything outside /admin goes to the console's overview. */
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <Routes>
          <Route path="/admin/*" element={<AdminApp />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
