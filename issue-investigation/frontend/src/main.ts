import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import "element-plus/theme-chalk/dark/css-vars.css";
import "./style.css";

import App from "./App.vue";
import ChatView from "./views/ChatView.vue";
import HistoryView from "./views/HistoryView.vue";
import DetailView from "./views/DetailView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "chat", component: ChatView },
    { path: "/history", name: "history", component: HistoryView },
    { path: "/runs/:id", name: "detail", component: DetailView },
  ],
});

createApp(App).use(router).use(ElementPlus).mount("#app");
