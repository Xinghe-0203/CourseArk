// T13：vue-router hash 模式路由表。
// 7 条主路由 name/path 与旧手写 hash 的 View key 完全一致（迁移零语义变化）；
// /mini 是 T14 Electron 迷你监控子窗的占位路由。
import { createRouter, createWebHashHistory, type RouteRecordRaw } from "vue-router";
// 页面级组件统一放 views/，components/ 只放可复用部件。
import OverviewDashboard from "./views/OverviewDashboard.vue";
import ProgressView from "./views/ProgressView.vue";
import TasksView from "./views/TasksView.vue";
import AccountsView from "./views/AccountsView.vue";
import CompletedView from "./views/CompletedView.vue";
import BankView from "./views/BankView.vue";
import SettingsView from "./views/SettingsView.vue";

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/overview" },
  {
    path: "/overview",
    name: "overview",
    component: OverviewDashboard,
    meta: { title: "工作总览" },
  },
  {
    path: "/progress",
    name: "progress",
    component: ProgressView,
    meta: { title: "课程进度" },
  },
  {
    path: "/tasks",
    name: "tasks",
    component: TasksView,
    meta: { title: "学习任务" },
  },
  {
    path: "/accounts",
    name: "accounts",
    component: AccountsView,
    meta: { title: "账号与课程" },
  },
  {
    path: "/completed",
    name: "completed",
    component: CompletedView,
    meta: { title: "已完成" },
  },
  {
    path: "/bank",
    name: "bank",
    component: BankView,
    meta: { title: "答题缓存" },
  },
  {
    path: "/settings",
    name: "settings",
    component: SettingsView,
    meta: { title: "偏好设置" },
  },
  {
    path: "/mini",
    name: "mini",
    // T14 迷你监控子窗；先占位避免未知路由告警。
    component: () => import("./views/MiniView.vue"),
    meta: { title: "迷你监控" },
  },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
