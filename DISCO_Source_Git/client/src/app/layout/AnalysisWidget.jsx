import React from 'react';
import RadialProfile from '../../widgets/RadialProfile';
import CumulativeFlux from '../../widgets/CumulativeFlux';
import SliceProfile from '../../widgets/SliceProfile';
import GaussianFit from '../../widgets/GaussianFit';
import Statistics from '../../widgets/Statistics';
import Histogram from '../../widgets/Histogram';

/** Render an analysis widget by id (shared by movable docks). */
export default function AnalysisWidget({ id }) {
  switch (id) {
    case 'radialProfile':
      return <RadialProfile />;
    case 'cumulative':
      return <CumulativeFlux />;
    case 'sliceProfile':
      return <SliceProfile />;
    case 'gaussianFit':
      return <GaussianFit />;
    case 'statistics':
      return <Statistics />;
    case 'histogram':
      return <Histogram />;
    default:
      return (
        <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
          Unknown panel.
        </div>
      );
  }
}
