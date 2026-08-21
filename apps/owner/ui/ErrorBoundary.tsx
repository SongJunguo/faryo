import { Component, h } from "preact";
import type { ComponentChildren } from "preact";

export class ErrorBoundary extends Component<
  { children: ComponentChildren; fallback: ComponentChildren; surface: string },
  { failed: boolean }
> {
  override state = { failed: false };

  static override getDerivedStateFromError() {
    return { failed: true };
  }

  override componentDidCatch() {
    // Do not echo component data: command labels and session metadata can be
    // private even though the source itself is public.
    console.error(`Faryo ${this.props.surface} UI failed`);
  }

  override render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
