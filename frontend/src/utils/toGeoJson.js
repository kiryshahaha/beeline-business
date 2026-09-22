export function ticketsToGeoJSON(tickets) {
  return {
    type: "FeatureCollection",
    features: tickets
      .filter(
        (ticket) =>
          ticket.location?.latitude != null &&
          ticket.location?.longitude != null
      )
      .map((ticket) => ({
        type: "Feature",
        properties: {
          id: ticket.id,
          title: ticket.title,
          description: ticket.description,
          work_type: ticket.work_type,
          status: ticket.status,
          address: ticket.location.address,
        },
        geometry: {
          type: "Point",
          coordinates: [
            ticket.location.longitude,
            ticket.location.latitude,
          ],
        },
      })),
  };
}