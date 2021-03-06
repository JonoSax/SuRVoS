

import h5py as h5
import numpy as np
from ..qt_compat import QtGui, QtCore, QtWidgets

import os
import logging as log

try:
    from tifffile import imsave as tiffsave
    tiff_enabled = True
except:
    tiff_enabled = False

from ..lib.io import MRC
from ..core import DataModel, LabelManager, Launcher
from ..widgets import HeaderLabel, RoundedWidget, TComboBox, HWidgets, \
                      SubHeaderLabel, ActionButton, FileWidget, SourceCombo

from .. import actions as ac
from .base import Plugin

from skimage.util import img_as_ubyte


class CheckableLevel(RoundedWidget):

    def __init__(self, level_id, level_name, parent=None):
        super(CheckableLevel, self).__init__(parent=parent, color=None,
                                         bg='#cde5e5', width=0)
        self.idx = level_id
        self.name = level_name

        hbox = QtWidgets.QHBoxLayout()
        self.setLayout(hbox)

        self.select = QtWidgets.QCheckBox()
        hbox.addWidget(self.select)

        self.name = QtWidgets.QLabel(level_name)
        self.name.setStyleSheet('font-size: 12pt; color: #009999;'
                                'font-weight: bold;')
        hbox.addWidget(self.name, 1)

        self.isChecked = self.select.isChecked
        self.setChecked = self.select.setChecked

    def mousePressEvent(self, ev):
        self.select.setChecked(not self.select.isChecked())

    def value(self):
        return self.idx


class Export(Plugin):

    name = 'Export'

    def __init__(self):
        super(Export, self).__init__(ptype=Plugin.Plugin)

        self.DM = DataModel.instance()
        self.LBLM = LabelManager.instance()
        self.launcher = Launcher.instance()

        self.addWidget(HeaderLabel('Export Segmentations'))
        dummy = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout()
        dummy.setLayout(vbox)
        self.addWidget(dummy)

        vbox.addWidget(SubHeaderLabel('Available Annotation Levels'))
        self.levels = {}
        self.container = QtWidgets.QWidget()
        self.container.setLayout(QtWidgets.QVBoxLayout())
        vbox.addWidget(self.container)

        vbox.addWidget(SubHeaderLabel('Export Levels'))
        self.output = FileWidget(folder=True)
        vbox.addWidget(HWidgets('Output Folder:', self.output, stretch=[0,1]))

        options = ['Raw Data', 'Raw Annotations', 'Segmentation Masks', 'Masked Data']
        self.combo = TComboBox('Output:', options, selected=0)
        self.combo.currentIndexChanged.connect(self.on_combo)
        vbox.addWidget(HWidgets(self.combo, None, stretch=[0,1]))

        self.source = SourceCombo()
        self.scale = QtWidgets.QCheckBox('Normalize')
        self.scale.setChecked(True)
        self.invert = QtWidgets.QCheckBox('Invert')
        self.scont = HWidgets(self.source, self.scale, self.invert, stretch=[1,0,0])
        self.scont.setVisible(False)
        vbox.addWidget(self.scont)

        formats = ['HDF5 (.h5)', 'MRC (.mrc)', 'Tiff Stack (.tiff)']
        self.format = TComboBox('Format:', formats, selected=0)
        self.overwrite = QtWidgets.QCheckBox('Overwrite')
        self.overwrite.setChecked(True)
        self.export = ActionButton('Export')
        vbox.addWidget(HWidgets(self.format, self.overwrite, self.export,
                                stretch=[1,0,0]))

        self.LBLM.levelAdded.connect(self.on_level_added)
        self.LBLM.levelLoaded.connect(self.on_level_added)
        self.LBLM.levelRemoved.connect(self.on_level_removed)
        self.export.clicked.connect(self.on_export)

    def on_combo(self, idx):
        self.scont.setVisible(idx == 3)

    def on_level_added(self, level, dataset):
        if level not in self.levels:
            obj = CheckableLevel(level, 'Level {}'.format(level))
            self.levels[level] = obj
            self.container.layout().addWidget(obj)

    def on_level_removed(self, level, dataset):
        if level in self.levels:
            self.levels[level].setParent(None)
            del self.levels[level]

    def on_export(self):
        levels = []
        for level in self.levels.values():
            if level.isChecked():
                levels.append(level.value())
        ftype = ['hdf5', 'mrc', 'tiff'][self.format.currentIndex()]
        otype = ['rdata', 'raw', 'mask', 'data'][self.combo.currentIndex()]
        owrite = self.overwrite.isChecked()
        dest = self.output.value()

        if otype == 'rdata':
            return self.save_raw_data('data', dest, ftype, owrite)

        self.launcher.setup('Exporting Levels')
        if not levels:
            self.launcher.error.emit("Please select a level!")
            return
        for level in levels:
            log.info('+ Exporting [Level {}]'.format(level))
            if otype == 'raw':
                self.save_raw(level, dest, ftype, owrite)
            elif otype == 'mask':
                self.save_mask(level, dest, ftype, owrite)
            else:
                self.save_data(level, dest, ftype, owrite, self.source.value(),
                               self.scale.isChecked(), self.invert.isChecked())
        self.launcher.cleanup()

    def save_raw(self, level, dest, ftype, owrite):
        log.info('+ Loading data into memory')
        dataset = self.LBLM.dataset(level)
        data = self.DM.load_ds(dataset)
        fname = os.path.basename(dataset)
        if isinstance(dest, str):
            outpath = os.path.join(dest, fname)
            if ftype == 'hdf5':
                attrs = self.DM.attrs(dataset)
                self.save_hdf5(outpath + '.h5', data, owrite=owrite, attrs=attrs)
            elif ftype == 'mrc':
                data = (data + 1).astype(np.int16)
                self.save_mrc(outpath + '.mrc', data, owrite=owrite)
            else:
                data = (data + 1).astype(np.int16)
                self.save_tiff(outpath + '.tif', data, owrite=owrite)
        else:
            self.launcher.error.emit("No output folder specified.")


    def save_mask(self, level, dest, ftype, owrite):
        log.info('+ Loading data into memory')
        dataset = self.LBLM.dataset(level)
        data = self.DM.load_ds(dataset)
        fname = os.path.basename(dataset)
        if isinstance(dest, str):
            for label in self.LBLM.labels(level):
                log.info('+ Saving [{}] from [Level {}]'.format(label.name, level))
                outpath = os.path.join(dest, '{}-mask{}'.format(fname, label.idx))
                mask = img_as_ubyte(data == label.idx)
                if ftype == 'hdf5':
                    self.save_hdf5(outpath + '.h5', mask, owrite=owrite)
                elif ftype == 'mrc':
                    self.save_mrc(outpath + '.mrc', mask, owrite=owrite)
                else:
                    self.save_tiff(outpath + '.tif', mask, owrite=owrite)
        else:
            self.launcher.error.emit("No output folder specified.")

    def save_data(self, level, dest, ftype, owrite, source_ds, scale=True, invert=False):
        log.info('+ Loading data into memory')
        dataset = self.LBLM.dataset(level)
        data = self.DM.load_ds(dataset)
        fname = os.path.basename(dataset)
        if isinstance(dest, str):
            source = self.DM.load_ds(source_ds)
            source[np.isinf(source)] = np.nan
            if invert:
                source = -source

            log.info('+ Extracting data stats')
            mask = ~np.isnan(source)
            amin = np.min(source[mask]); amax = np.max(source[mask]);
            if scale:
                source[mask] -= amin
                source[mask] /= (amax - amin)
                source[~mask] = 0
                amin = 0; amax = 1;
            amean = source.mean()

            fillval = amax if invert else amin

            for label in self.LBLM.labels(level):
                log.info('+ Saving [{}] from [Level {}]'.format(label.name, level))
                outpath = os.path.join(dest, '{}-data{}'.format(fname, label.idx))
                mask = (data == label.idx)
                final = np.full(source.shape, fillval, np.float32)
                final[mask] = source[mask]

                if ftype == 'hdf5':
                    attrs = self.DM.attrs(source_ds)
                    self.save_hdf5(outpath + '.h5', final, owrite=owrite, attrs=attrs)
                elif ftype == 'mrc':
                    self.save_mrc(outpath + '.mrc', final, owrite=owrite)
                else:
                    self.save_tiff(outpath + '.tif', final, owrite=owrite)
        else:
            self.launcher.error.emit("No output folder specified.")

    def save_raw_data(self, dataset, dest, ftype, owrite):
        log.info('+ Loading data into memory')
        data = self.DM.load_ds(dataset)
        data -= data.min()
        data /= data.max()

        fname = os.path.basename(dataset)

        if isinstance(dest, str):
            outpath = os.path.join(dest, fname)
            if ftype == 'hdf5':
                attrs = self.DM.attrs(dataset)
                self.save_hdf5(outpath + '.h5', data, owrite=owrite, attrs=attrs)
            elif ftype == 'mrc':
                stats = (data.min(), data.max(), data.mean())
                self.save_mrc(outpath + '.mrc', data, owrite=owrite, stats=stats)
            else:
                self.save_tiff(outpath + '.tif', data, owrite=owrite)
        else:
            self.launcher.error.emit("No output folder specified.")

    def check_owrite(self, path, flag=False):
        if flag:
            return True
        if os.path.isfile(path):
            err_msg = 'Destination dataset [{}] already exists, '\
                      'do you want to overwrite it?'.format(path)
            ans = QtWidgets.QMessageBox.question(self, "Error", err_msg,
                                             QtWidgets.QMessageBox.Yes,
                                             QtWidgets.QMessageBox.No)
            if ans == QtWidgets.QMessageBox.No:
                log.info('  -- Skipping')
                return False
        return True

    def save_hdf5(self, outpath, data, owrite=True, attrs=None):
        if not self.check_owrite(outpath, owrite):
            return
        log.info(' * Writing file [{}]'.format(outpath))
        with h5.File(outpath, 'w') as f:
            d = f.create_dataset('data', data=data)
            if attrs is not None:
                for k, v in attrs.items():
                    d.attrs[k] = v

    def save_mrc(self, outpath, data, owrite=True, stats=None):
        if not self.check_owrite(outpath, owrite):
            return

        log.info(' * Writing file [{}]'.format(outpath))
        MRC(data, stats=stats).save(outpath)

    def save_tiff(self, outpath, data, owrite=True):
        if not tiff_enabled:
            raise Exception('`tifffile` library not available')

        log.info(' * Writing file [{}]'.format(outpath))
        tiffsave(outpath, data)
