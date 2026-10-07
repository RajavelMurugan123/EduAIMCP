import api from "./client";

export async function askLibrary(message) {
  const response = await api.post("/library/chat", { message });
  return response.data;
}