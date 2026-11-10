import "./styles.css";
import { App } from "./app";

const root = document.getElementById("app");
if (root) {
  const app = new App(root);
  void app.start();
  (window as unknown as { udsbench?: App }).udsbench = app;
}
