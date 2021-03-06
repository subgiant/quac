#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
	Generate the figures we use in our paper. This code is essentially a modified version of lag_analysis_regression.py.
	It first computes correlations and fits the models, and then it generates figures.
"""

# Copyright (c) Los Alamos National Security, LLC and others.

from __future__ import print_function, division
import argparse
import csv
import sys
import datetime
from collections import OrderedDict
from operator import itemgetter
from scipy import stats
from dateutil.parser import parse
import math
import statsmodels.api as sm
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.ticker import FormatStrFormatter, MultipleLocator, NullFormatter
from matplotlib.font_manager import FontProperties
import matplotlib.dates as mdates
import subprocess

argparser = argparse.ArgumentParser(description='Perform ±28 day lagged regressions to determine how Wikipedia and ground truth data are related.')
argparser.add_argument('raw_wikipedia_counts_csv',
                       type=argparse.FileType('rU'),
                       help='CSV file containing raw Wikipedia counts')
argparser.add_argument('ground_truth_csv',
                       type=argparse.FileType('rU'),
                       help='CSV file containing date,value ground truth data')
argparser.add_argument('incidence_model_accesses_graph_pdf',
                       help='PDF file to output graph showing incidence, model, and wiki accesses')
argparser.add_argument('lag_graph_pdf',
                       help='PDF file to output lagged model R^2')
argparser.add_argument('-ap', '--aggregate-period',
                       type=str,
                       help='select whether the aggregate period is BEFORE or AFTER the specified date (e.g., does date 2012-09-14 mean we aggregate from [2012-09-07 to 2012-09-14] or [2012-09-14 to 2012-09-21]?)',
                       choices=['before', 'after'],
                       default='after')
argparser.add_argument('--legend',
                       type=str,
                       help='if present, location for legend, otherwise no legend')
argparser.add_argument('--title',
                       type=str,
                       help='if present, text of model plot title')
argparser.add_argument('--title-loc',
                       type=str,
                       default='upper left',
                       help='location of title')
argparser.add_argument('--lagx',
                       action='store_true',
                       help='draw X axis labels on lag plot')
argparser.add_argument('--lagy',
                       action='store_true',
                       help='draw Y axis labels on lag plot')
argparser.add_argument('--lagtitle',
                       type=str,
                       help='if present, text of lag plot title')
argparser.add_argument('--incidencex',
                       action='store_true',
                       help="draw X axis label ('Date') on incidence plot")
argparser.add_argument('--incidence-y1-label',
                       type=str,
                       default='Disease Incidence',
                       help="label to use for the incidence plot's Y1 axis")
argparser.add_argument('--strip-last-xlabel',
                       action='store_true')
args = argparser.parse_args()

#first, read the raw wiki data and aggregate each article's counts by day since that's the resolution we want
project_article_date_count = dict() #en -> flu -> 10/12/09 -> 14
project_date_count = dict() #en -> 10/12/09 -> 9000000
project_articles = set()
with args.raw_wikipedia_counts_csv as wiki_csv:
	reader = csv.reader(wiki_csv)

	#first deal with the headers
	index_project_article = dict() #map header index to (project, article) tuple (e.g., 1 -> (en, Flu), 2 -> (en, Human_flu))
	headers = reader.next()
	for index, header in enumerate(headers):
		if header != 'timestamp':
			header_split = header.split('-')
			if len(header_split) >= 2:
				project = header_split[0]
				article = ''.join(header_split[1:])

				project_articles.add((project, article))

				#initialize dicts that store the wiki data
				if project not in project_article_date_count:
					project_article_date_count[project] = dict()
					project_date_count[project] = OrderedDict() #ordered by date
				if article not in project_article_date_count[project]:
					project_article_date_count[project][article] = OrderedDict() #ordered by date

				index_project_article[index] = (project, article)
			elif len(header_split) == 1:
				project = header_split[0]
				index_project_article[index] = (project, None)
	
	#now read the data
	for row in reader:
		#don't forget to account for off-by-one hour issue since hourly timestamps mark the END of the hour
		#date = (datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') - datetime.timedelta(hours=1)).date()
		date = (parse(row[0]) - datetime.timedelta(hours=1)).date()

		for index, value in enumerate(row):
			#skip timestamp since we've already read it
			if index == 0:
				continue

			project, article = index_project_article[index]

			#article will be None if it's the project total count
			if article:
				if date not in project_article_date_count[project][article]:
					project_article_date_count[project][article][date] = 0
				project_article_date_count[project][article][date] += int(value)
			else:
				if date not in project_date_count[project]:
					project_date_count[project][date] = 0
				project_date_count[project][date] += int(value)

#now read the ground truth data
ground_truth_date_count = OrderedDict() #ordered by date
with args.ground_truth_csv as ground_truth_csv:
	reader = csv.reader(ground_truth_csv)

	for row in reader:
		#date = datetime.datetime.strptime(row[0], '%Y-%m-%d').date()
		date = parse(row[0]).date()

		if date in ground_truth_date_count:
			raise ValueError('date [%s] present multiple times in ground truth CSV' % date)
		ground_truth_date_count[date] = float(row[1])

def get_date_normalized_wiki_count(project, article, offset_days=0):
	"""
		This function aggregates wiki counts according to ground truth data with an optional offset. The offset shifts the wiki data
		one way or another relative to the ground truth data.
	"""

	#generate list of offset dates
	offset_ground_truth_dates = [(x + datetime.timedelta(days=offset_days)) for x in ground_truth_date_count.keys() if (x + datetime.timedelta(days=offset_days)) in project_article_date_count[project][article]]
	offset_ground_truth_dates_iterator = iter(offset_ground_truth_dates)

	#construct new normalized shifted time series
	start_date = next(offset_ground_truth_dates_iterator)
	current_date = start_date
	next_date = next(offset_ground_truth_dates_iterator)
	last_date = offset_ground_truth_dates[-1]
	date_normalized_wiki_count = OrderedDict()
	current_total_project_accesses = 0
	while start_date <= last_date:
		#we've hit the next date so finalize the normalization, shift dates, and reset counters
		if current_date == next_date:
			#don't forget to deal with the aggregate period here
			if args.aggregate_period == 'after':
				if current_total_project_accesses != 0:
					date_normalized_wiki_count[start_date] /= current_total_project_accesses
				else:
					date_normalized_wiki_count[start_date] = 0
			else:
				if current_total_project_accesses != 0:
					date_normalized_wiki_count[next_date] /= current_total_project_accesses
				else:
					date_normalized_wiki_count[next_date] = 0

			start_date = next_date
			next_date = next(offset_ground_truth_dates_iterator, None)
			current_total_project_accesses = 0

			if not next_date:
				break

		#add counts for this time frame
		#the aggregate period is handled here: we still count the same values, but the values get associated with next_date instead of start_date
		if args.aggregate_period == 'after':
			if start_date not in date_normalized_wiki_count:
				date_normalized_wiki_count[start_date] = 0
				
			date_normalized_wiki_count[start_date] += project_article_date_count[project][article][current_date]
			current_total_project_accesses += project_date_count[project][current_date]
		else:
			if next_date not in date_normalized_wiki_count:
				date_normalized_wiki_count[next_date] = 0

			date_normalized_wiki_count[next_date] += project_article_date_count[project][article][current_date]
			current_total_project_accesses += project_date_count[project][current_date]

		current_date += datetime.timedelta(days=1)
	
	return date_normalized_wiki_count

#find top 10 correlated articles
article_correlations = dict() #article to correlation
for project, article in project_articles:
	date_normalized_wiki_count = get_date_normalized_wiki_count(project, article)
	
	#pull ground truth values only for the dates that are in agreement with the wiki values
	#these are the values we use to correlate with the wiki values
	corresponding_ground_truth_count = OrderedDict([(x, ground_truth_date_count[x]) for x in date_normalized_wiki_count])

	#compute correlation
	correlation = stats.pearsonr(date_normalized_wiki_count.values(), corresponding_ground_truth_count.values())[0]

	if not math.isnan(correlation):
		article_correlations[(project, article)] = correlation

article_correlations = sorted(article_correlations.iteritems(), key=lambda x: abs(x[1]), reverse=True)[:10]

#now we can do the lagged regression analysis
lag_model = dict() #map lag to regression model
lag_results = dict() #map lag to model fit results

offset = -28
while offset <= 28:
	y = None
	X = list()

	for (project, article), _ in article_correlations:
		date_normalized_wiki_count = get_date_normalized_wiki_count(project, article, offset)

		#add new variable
		X.append(date_normalized_wiki_count.values())

		#pull ground truth values only for the dates that are in agreement with the wiki values
		#note that this only needs to be done once since all the articles will use the same dates
		if not y:
			corresponding_ground_truth_count = OrderedDict([(x - datetime.timedelta(days=offset), ground_truth_date_count[x - datetime.timedelta(days=offset)]) for x in date_normalized_wiki_count])
			y = corresponding_ground_truth_count.values()

	#transpose X
	X = [list(x) for x in zip(*X)]

	#add intercept column
	X = sm.add_constant(X, prepend=True)

	#now run regression
	model = sm.OLS(y, X)
	results = model.fit()

	lag_model[offset] = model
	lag_results[offset] = results

	offset += 1

#draw incidence, accesses, and model values
#set global font to Helvetica Neue
mpl.rcParams['font.family'] = 'sans-serif'
mpl.rcParams['mathtext.default'] = 'regular'
# On Linux, causes: UserWarning: findfont: Font family ['sans-serif'] not found"
# Note that Helvetica Neue is not available on Linux anyway.
#mpl.rcParams['font.sans-serif'] = 'Helvetica Neue'

mpl.rcParams['axes.linewidth'] = 0.5

y_font = FontProperties(fname='../paper/Inconsolata.ttf')
x_font = y_font

fig = plt.figure(figsize=(6.3,1.8))  # note: height is an overestimate...
axwik = fig.add_subplot(111)
axmod = axwik.twinx()
#axmod = fig.add_subplot(111)
#axwik = axmod.twinx()

# The second list argument is so that we can normalize a paired sequence to
# the larger of the two.
def gnormalize(list_, list2=[float('-inf')]):
        max_ = max(max(list_), max(list2))
        return [x / max_ for x in list_]

def article_color(r):
        # 0 = black, 1 = white
        return '0.75'
        #cmax = 0.5
        #cmin = 1.0
        #return str(cmin + (cmax - cmin) * abs(r))

#plot best correlated article counts
for index, ((project, article), correlation) \
    in enumerate(list(reversed(article_correlations))[:5]):
	date_normalized_wiki_count = get_date_normalized_wiki_count(project, article)

	(wikipedia_accesses_plot,) = \
           axwik.plot(date_normalized_wiki_count.keys(),
                    gnormalize(date_normalized_wiki_count.values()),
                    label='Wikipedia Accesses',
                    color=article_color(correlation),
                    linestyle='-',
                    linewidth=0.5)

#draw ground truth
xs = ground_truth_date_count.keys()
#ys = gnormalize(ground_truth_date_count.values(), lag_results[0].predict())
ys = ground_truth_date_count.values()
if (args.aggregate_period == 'after'):
        xs = xs[:-1]
        ys = ys[:-1]
else:
        xs = xs[1:]
        ys = ys[1:]
(ground_truth_plot,) = axmod.plot(xs,
                                  ys,
                                  label='Ground Truth',
                                  color='#377eb8',
                                  linestyle='-',
                                  linewidth=2.0)

#plot predicted values
dates = get_date_normalized_wiki_count(article_correlations[0][0][0],
                                       article_correlations[0][0][1]).keys()
(linear_model_plot,) = axmod.plot(dates,
                                  lag_results[0].predict(),
                                  label='Linear Model',
                                  color='#a65628',
                                  linestyle='-',
                                  linewidth=1.5)

#left axis options
axmod.set_ylim(bottom=0)
axmod.tick_params(bottom='on', labelbottom='on',
                  top='off', labeltop='off',
                  left='on', labelleft='on',
                  right='off', labelright='off',
                  labelsize=7)
axmod.yaxis.tick_left()
axmod.yaxis.set_label_position('left')
axmod.yaxis.set_offset_position('left')
axmod.set_ylabel(args.incidence_y1_label, fontsize=6)
if args.incidencex:
    axmod.set_xlabel('', fontsize=6)
#if there are few enough cases, matplotlib will use fractional tick labels
if max(ys) < 6:
    axmod.yaxis.set_major_locator(MultipleLocator(base=1.0))
axmod.set_yticklabels(axmod.get_yticks(), fontproperties=y_font)
axmod.yaxis.set_major_formatter(FormatStrFormatter('%6d'))
axmod.yaxis.set_tick_params(length=2)
axmod.xaxis.set_visible(True)
axmod.xaxis.set_major_locator(mdates.YearLocator())
axmod.xaxis.set_minor_locator(mdates.MonthLocator([1, 4, 7, 10]))
#axmod.set_xticklabels(axmod.get_xticks(), fontproperties=x_font)
axmod.xaxis.set_major_formatter(mdates.DateFormatter('            %Y'))
axmod.xaxis.set_minor_formatter(NullFormatter())
axmod.xaxis.set_tick_params(which='major', direction='out', pad=-3, length=7)
axmod.xaxis.set_tick_params(which='minor', direction='out', top='off', length=2)
if (args.strip_last_xlabel):
    axmod.xaxis.get_major_ticks()[-1].label1.set_visible(False)

#right axis options
axwik.set_ylim(bottom=0)
axwik.tick_params(bottom='on', labelbottom='off',
                  top='off', labeltop='off',
                  left='off', labelleft='off',
                  right='off', labelright='off',
                  labelsize=6)
axwik.yaxis.tick_right()
axwik.yaxis.set_label_position('right')
axwik.yaxis.set_offset_position('right')
axwik.set_ylabel('Article accesses', fontsize=6) #, rotation=270)
axwik.yaxis.set_ticks([0, 1])
axwik.set_yticklabels(axwik.get_yticks(), fontproperties=y_font)
axwik.yaxis.set_tick_params(labelsize=6)
axwik.xaxis.set_visible(False)
#axwik.xaxis.set_minor_formatter(NullFormatter())

#top/bottom axis options
fig.autofmt_xdate(rotation=0, ha='center')

# legend
if (args.legend):
        lgd = axwik.legend([ground_truth_plot,
                            linear_model_plot,
                            wikipedia_accesses_plot],
                           ['Official', 'Model', 'Wikipedia'],
                           args.legend,
                           ncol=3,
                           prop={'size':   7,
                                 'weight': 'normal'},
                           bbox_to_anchor=(0.5, -0.35),
        )

        #set line with on legend border
        fr = lgd.get_frame()
        fr.set_lw(0.5)

# title
if (args.title):
        if (args.title_loc == 'lower center'):
                x = 0.5
                y = 0.001
                ha='center'
                va='bottom'
        elif (args.title_loc == 'lower left'):
                x = 0.005
                y = 0.001
                ha='left'
                va='bottom'
        elif (args.title_loc == 'lower right'):
                x = 0.995
                y = 0.001
                ha='right'
                va='bottom'
        elif (args.title_loc == 'upper center'):
                x = 0.5
                y = 0.99
                ha='center'
                va='top'
        elif (args.title_loc == 'upper left'):
                x = 0.005
                y = 0.99
                ha='left'
                va='top'
        elif (args.title_loc == 'upper right'):
                x = 0.995
                y = 0.99
                ha='right'
                va='top'
        axwik.text(x, y, args.title,
                   size=7,
                   weight='bold',
                   ha=ha,
                   va=va,
                   transform=axwik.transAxes)


#plt.show()
fig.savefig(args.incidence_model_accesses_graph_pdf,
            transparent=True,
            bbox_inches='tight',
            pad_inches=0.05,
            format='pdf')
del fig
subprocess.check_call(['pdfcrop',
                       args.incidence_model_accesses_graph_pdf,
                       args.incidence_model_accesses_graph_pdf])

#now draw the lagged R^2 figure
fig = plt.figure(figsize=(3.35,2))
axlag = fig.add_subplot(111)

rsquareds = [lag_results[x].rsquared for x in sorted(lag_results)]
rsquareds.reverse()

axlag.plot(range(-28, 29),
           rsquareds,
           color='#377eb8',
           linestyle='-',
           linewidth=2.0)
# Really the vline should go on top of the plot because it's part of the axes,
# but order doesn't seem to affect that.
axlag.vlines(0, 0, 1, linestyles='dashed', linewidth=0.5)
axlag.tick_params(labelbottom='off',
                labelleft='off')
# FIXME: If the axis labels are hidden, then the subfigures don't line up in
# the LaTeX file. One possible workaround is to draw the labels in white and
# then crop them in LaTeX.
if (args.lagx or True):
        axlag.set_xlabel('Forecast (days)', size=8)
        axlag.tick_params(labelbottom='on')
if (args.lagy or True):
        axlag.set_ylabel(r'$r^2$', size=8, rotation='horizontal')
        axlag.tick_params(labelleft='on')
axlag.set_ylim(bottom=0, top=1)
axlag.set_xlim(left=-28, right=28)
axlag.set_xticks([-28, -21, -14, -7, 0, 7, 14, 21, 28])
axlag.tick_params(axis='both', labelsize=7)
# This makes the plots different sizes depending on whether axes are shown.
#fig.tight_layout()

# title
if (args.title):
        axlag.text(0.96, 0.07, args.lagtitle,
                   size=9,
                   weight='bold',
                   ha='right',
                   va='bottom',
                   transform=axlag.transAxes)

fig.savefig(args.lag_graph_pdf,
            transparent=True,
            bbox_inches='tight',
            pad_inches=0.02,
            format='pdf')
