import React, { useState } from 'react';
import { HourlySurveillanceActivity } from '../types';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from 'recharts';

interface AnalyticsViewProps {
  hourlyData: HourlySurveillanceActivity[];
}

const COLORS = {
  people: '#356B7A',
  vehicles: '#4C8B8B',
  alerts: '#B84C4C',
  breaches: '#B88735',
};

const HEATMAP_LEVELS = [
  { max: 20, bg: '#E7EEEC', text: '#66757A', label: 'Minimal' },
  { max: 40, bg: '#DDECEA', text: '#356B7A', label: 'Low' },
  { max: 60, bg: '#DDECEA', text: '#3E7655', label: 'Normal' },
  { max: 80, bg: '#F5EDD5', text: '#B88735', label: 'Active' },
  { max: 101, bg: '#F2DEDE', text: '#B84C4C', label: 'Peak' },
];

function getHeatColor(val: number) {
  for (const lvl of HEATMAP_LEVELS) {
    if (val < lvl.max) return lvl;
  }
  return HEATMAP_LEVELS[HEATMAP_LEVELS.length - 1];
}

export const AnalyticsView: React.FC<AnalyticsViewProps> = ({ hourlyData }) => {
  const [activeTab, setActiveTab] = useState<
    'OVERVIEW' | 'PEOPLE' | 'VEHICLES' | 'ALERTS'
  >('OVERVIEW');

  const chartData = hourlyData.map((h) => ({
    hour: h.hour,
    People: h.peopleCount,
    Vehicles: h.vehicleCount,
    Alerts: h.alertsCount,
    Breaches: h.intrusionBreaches,
    Density: h.totalDensity,
  }));

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">
              monitoring
            </span>
            Surveillance Analytics
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">
            24-hour activity trends · Incident charts · Density heatmap
          </p>
        </div>
        <span className="text-[11px] font-semibold text-on-surface-variant flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-on-surface-variant" /> NO DATA YET
        </span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-outline-variant bg-surface rounded-t-xl overflow-x-auto">
        {[
          { id: 'OVERVIEW', label: 'Overview', icon: 'dashboard' },
          { id: 'PEOPLE', label: 'People', icon: 'groups' },
          { id: 'VEHICLES', label: 'Vehicles', icon: 'directions_car' },
          { id: 'ALERTS', label: 'Alerts', icon: 'crisis_alert' },
                  ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2.5 text-[11px] font-bold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer whitespace-nowrap ${
              activeTab === tab.id
                ? 'border-primary text-primary bg-primary/5'
                : 'border-transparent text-on-surface-variant hover:text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">
              {tab.icon}
            </span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Main Chart */}
      <div className="bg-surface border border-outline-variant rounded-xl p-4">
        <div className="text-[13px] font-bold text-on-surface mb-4">
          {activeTab === 'OVERVIEW' && '24-Hour Combined Border Activity'}
          {activeTab === 'PEOPLE' && 'Person Detection Trends'}
          {activeTab === 'VEHICLES' && 'Vehicle & ANPR Volume'}
          {activeTab === 'ALERTS' && 'Security Alerts'}
                  </div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <defs>
              <linearGradient id="gradPeople" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS.people} stopOpacity={0.3} />
                <stop offset="95%" stopColor={COLORS.people} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gradVehicles" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS.vehicles} stopOpacity={0.3} />
                <stop offset="95%" stopColor={COLORS.vehicles} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gradAlerts" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS.alerts} stopOpacity={0.3} />
                <stop offset="95%" stopColor={COLORS.alerts} stopOpacity={0} />
              </linearGradient>
                          </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#D4DEDC" />
            <XAxis
              dataKey="hour"
              tick={{ fontSize: 10, fill: '#66757A' }}
              stroke="#D4DEDC"
            />
            <YAxis tick={{ fontSize: 10, fill: '#66757A' }} stroke="#D4DEDC" />
            <Tooltip
              contentStyle={{
                background: '#FCFDFC',
                border: '1px solid #D4DEDC',
                borderRadius: 8,
                fontSize: 11,
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
            />

            {(activeTab === 'OVERVIEW' || activeTab === 'PEOPLE') && (
              <Area
                type="monotone"
                dataKey="People"
                stroke={COLORS.people}
                strokeWidth={2}
                fill="url(#gradPeople)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2 }}
              />
            )}
            {(activeTab === 'OVERVIEW' || activeTab === 'VEHICLES') && (
              <Area
                type="monotone"
                dataKey="Vehicles"
                stroke={COLORS.vehicles}
                strokeWidth={2}
                fill="url(#gradVehicles)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2 }}
              />
            )}
            {(activeTab === 'OVERVIEW' || activeTab === 'ALERTS') && (
              <Area
                type="monotone"
                dataKey="Alerts"
                stroke={COLORS.alerts}
                strokeWidth={2}
                fill="url(#gradAlerts)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2 }}
              />
            )}
                      </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Bottom: Bar Chart + Heatmap */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Bar Chart */}
        <div className="bg-surface border border-outline-variant rounded-xl p-4">
          <div className="text-[13px] font-bold text-on-surface mb-4">
            Night Curfew Breach Incidents
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#D4DEDC" />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 10, fill: '#66757A' }}
                stroke="#D4DEDC"
              />
              <YAxis tick={{ fontSize: 10, fill: '#66757A' }} stroke="#D4DEDC" />
              <Tooltip
                contentStyle={{
                  background: '#FCFDFC',
                  border: '1px solid #D4DEDC',
                  borderRadius: 8,
                  fontSize: 11,
                }}
              />
              <Bar dataKey="Breaches" radius={[4, 4, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.Breaches > 2 ? COLORS.alerts : COLORS.breaches}
                    fillOpacity={0.8}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Heatmap */}
        <div className="bg-surface border border-outline-variant rounded-xl p-4">
          <div className="text-[13px] font-bold text-on-surface mb-4">
            24-Hour Activity Heatmap
          </div>
          <div className="grid grid-cols-6 sm:grid-cols-12 gap-1.5 mt-4">
            {hourlyData.map((h) => {
              const d = h.totalDensity;
              const lvl = getHeatColor(d);
              return (
                <div
                  key={h.hour}
                  className="p-2 flex flex-col items-center justify-center rounded-lg border border-outline-variant/40 transition-transform hover:scale-105 cursor-pointer"
                  style={{ backgroundColor: lvl.bg, color: lvl.text }}
                  title={`${h.hour} UTC — ${d}% — ${lvl.label}`}
                >
                  <span className="font-mono text-[8px] font-bold">{h.hour}</span>
                  <span className="font-mono text-[9px] font-extrabold">{d}%</span>
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-between text-[10px] text-on-surface-variant pt-3 mt-3 border-t border-outline-variant">
            <div className="flex items-center gap-2">
              {HEATMAP_LEVELS.slice(0, 4).map((lvl, i) => (
                <React.Fragment key={i}>
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: lvl.bg, border: '1px solid #D4DEDC' }}
                  />{' '}
                  {lvl.label}
                </React.Fragment>
              ))}
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: HEATMAP_LEVELS[4].bg, border: '1px solid #D4DEDC' }}
              />{' '}
              Peak
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
