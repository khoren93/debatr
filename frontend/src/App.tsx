import { Suspense, lazy } from 'react';
import { Route, Routes, useParams } from 'react-router';
import { AppShell, Page } from './components/layout/AppShell';
import { AuthProvider } from './auth/AuthContext';
import { RequireAuth } from './auth/RequireAuth';
import { LinkButton, PageLoader } from './components/ui';
import Landing from './pages/Landing';
import Library from './pages/Library';
import Gallery from './pages/Gallery';
import Leaderboard from './pages/Leaderboard';
import Topic from './pages/Topic';
import Account from './pages/Account';
import Login from './pages/Login';
import Register from './pages/Register';
import Device from './pages/Device';

// The wizard and the debate page are the heaviest pages: load them lazily.
const CreateDebate = lazy(() => import('./pages/CreateDebate'));
const DebateView = lazy(() => import('./pages/DebateView'));

const NotFound = () => (
  <Page className="text-center">
    <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">404</div>
    <h1 className="mt-2 font-display text-4xl font-extrabold tracking-tight">Page not found</h1>
    <p className="mt-3 text-muted">The page you are looking for does not exist.</p>
    <div className="mt-6">
      <LinkButton to="/" variant="secondary">
        Back home
      </LinkButton>
    </div>
  </Page>
);

// Keyed by id so navigating between debates resets the page state.
const DebateRoute = () => {
  const { id } = useParams<{ id: string }>();
  return <DebateView key={id} id={id ?? ''} />;
};

const PublicDebateRoute = () => {
  const { slug } = useParams<{ slug: string }>();
  return <DebateView key={`slug:${slug}`} slug={slug ?? ''} />;
};

// The admin console (/admin) is a separate SPA: src/admin-main.tsx, built by vite.admin.config.ts.
const App = () => (
  <AuthProvider>
    <AppShell>
      <Suspense fallback={<PageLoader />}>
        <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/gallery" element={<Gallery />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/d/:slug" element={<PublicDebateRoute />} />
        <Route path="/t/:slug" element={<Topic />} />
        <Route path="/debate/:id" element={<DebateRoute />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/library"
          element={
            <RequireAuth>
              <Library />
            </RequireAuth>
          }
        />
        <Route
          path="/create"
          element={
            <RequireAuth>
              <CreateDebate />
            </RequireAuth>
          }
        />
        <Route
          path="/account"
          element={
            <RequireAuth>
              <Account />
            </RequireAuth>
          }
        />
        <Route
          path="/device"
          element={
            <RequireAuth>
              <Device />
            </RequireAuth>
          }
        />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </AppShell>
  </AuthProvider>
);

export default App;
