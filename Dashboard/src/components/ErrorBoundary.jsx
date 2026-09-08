import React from "react";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Dashboard rendering error", { error, info });
  }

  render() {
    if (this.state.error) {
      return (
        <main className="fatal-error-shell" role="alert">
          <section className="fatal-error-panel">
            <strong>Dashboard non caricata</strong>
            <p>Si e' verificato un errore nell'interfaccia. Aggiorna la pagina o riavvia la dashboard.</p>
            <small>{this.state.error?.message ?? "Errore non specificato"}</small>
            <button type="button" onClick={() => window.location.reload()}>
              Ricarica pagina
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
