# 前端镜像：node 构建 → nginx 静态服务
# 审查 P1（2026-09-24）：npm install → npm ci——按 lockfile 可复现安装（缓存友好）
FROM node:20-alpine AS build
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
