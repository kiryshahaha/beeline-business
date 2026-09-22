import { useControl } from "@vis.gl/react-maplibre";
import { GlobeControl } from "maplibre-gl";

export const ProjectionControl = () => {
  useControl(() => new GlobeControl());
  return;
};
