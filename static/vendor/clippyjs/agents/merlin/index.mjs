const Merlin = {
	agent: () => import("./agent.mjs"),
	sound: () => import("./sounds-mp3.mjs"),
	map: () => import("./map.mjs")
};
export { Merlin as default };
